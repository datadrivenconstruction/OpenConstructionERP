// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Removing something raised in error.
 *
 * The register had no way back: a mis-keyed RFQ sat there forever beside
 * the real ones that still needed emailing, and the only fix was a DELETE
 * straight against the database. The rail the server now enforces has two
 * tiers, and the difference is whether anybody outside the building has
 * seen it:
 *
 *   nothing sent, no quotes, no replies, nothing raised from it
 *       -> DELETE. It never really existed.
 *   anything else
 *       -> WITHDRAW, with a written reason. It stays on the record,
 *          marked withdrawn, and drops out of the open lists.
 *
 * The UI must be honest BEFORE the server answers, so "Withdraw…" is
 * offered outright on anything already emailed - and when a delete is
 * refused, the 409 is not dumped as an error toast. It becomes the
 * withdraw dialog, pre-explaining, in the server's own words, why the
 * item cannot simply be deleted. One refusal, one door, no dead end.
 */

import type { CSSProperties } from 'react';
import type { TFunction } from 'i18next';
import type { QueryClient } from '@tanstack/react-query';

import { qAsk, qConfirm } from './qAsk';
import type { MenuItem } from './ContextMenu';
import {
  deleteItem,
  errorDetail,
  isWithdrawn,
  removeRefusal,
  withdrawItem,
  type RegisterItemRow,
} from './registers-api';

export { isWithdrawn };

/** The bare shape either flow needs - so the tracking rows can call it too. */
export interface RemovableItem {
  id: string;
  reference: string;
  status?: string;
  fields?: Record<string, unknown>;
  withdrawn_at?: string | null;
  withdrawn_by?: string | null;
  withdrawn_reason?: string | null;
}

export interface RemoveCtx {
  t: TFunction;
  addToast: (toast: { type: 'success' | 'error'; title: string }) => void;
  queryClient: QueryClient;
  projectId: string | null;
  /** Called once the item is gone from the list, to collapse an open row. */
  onGone?: (itemId: string) => void;
}

/** What happened, for the caller and for the tests. */
export type RemoveOutcome = 'deleted' | 'withdrawn' | null;

/**
 * Has anything gone out on this item? The row already knows - the send
 * log rides on it - so the menu can offer "Withdraw…" without a round
 * trip. Deliberately generous: award, quotes and replies all imply a
 * send, and the server has the final word either way.
 */
export function wasEmailed(item: RemovableItem): boolean {
  const log = (item.fields as Record<string, unknown> | undefined)?.['_send_log'];
  return Array.isArray(log) && log.length > 0;
}

/** "Withdrawn 03/09/2026 by Alex Example — raised against the wrong job". */
export function withdrawnNote(item: RemovableItem, t: TFunction): string {
  const when = (item.withdrawn_at ?? '').slice(0, 10);
  const who = (item.withdrawn_by ?? '').trim();
  const why = (item.withdrawn_reason ?? '').trim();
  const head = who
    ? t('ci.rm_wd_by', { defaultValue: 'Withdrawn {{when}} by {{who}}', when: when || '—', who })
    : t('ci.rm_wd_on', { defaultValue: 'Withdrawn {{when}}', when: when || '—' });
  return why ? `${head} — ${why}` : head;
}

// ---------------------------------------------------------------------------
// The flows
// ---------------------------------------------------------------------------

const invalidate = (ctx: RemoveCtx, itemId: string) => {
  for (const key of [
    ['registers', ctx.projectId],
    ['register-tracking', ctx.projectId],
    ['item-tracking', itemId],
    ['thread', itemId],
  ]) {
    void ctx.queryClient.invalidateQueries({ queryKey: key });
  }
};

/**
 * Withdraw it, asking for the reason - and KEEP ASKING while the server
 * refuses the words. The reason is validated server-side ("x" is not a
 * reason), so firing once and toasting the refusal both loses the typing
 * and leaves the item exactly where it was. Same shape as the quote-gate
 * override above: the refusal becomes the next dialog's note, and what
 * was typed comes back in the field.
 *
 * `lead` / `reasons` are what a refused DELETE said, so the dialog can
 * explain why deleting was not on offer before asking anything.
 */
export async function withdrawFlow(
  item: RemovableItem,
  ctx: RemoveCtx,
  refusal?: { error: string; reasons: string[] },
): Promise<RemoveOutcome> {
  const { t, addToast } = ctx;
  const because = (refusal?.reasons ?? []).map((r) => `• ${r}`).join('\n');
  const lead =
    refusal?.error ||
    (refusal
      ? t('ci.rm_cannot_delete', {
          defaultValue: '{{r}} has already been seen outside the building, so it cannot be deleted.',
          r: item.reference,
        })
      : '');
  const tail = t('ci.rm_wd_explain', {
    defaultValue:
      'Withdrawing keeps it on the record with your reason, marks it withdrawn and takes it out of the open lists.',
  });
  let note = [lead, because, tail].filter(Boolean).join('\n');
  let typed = '';

  for (;;) {
    const answers = await qAsk({
      title: t('ci.rm_wd_title', { defaultValue: 'Withdraw {{r}}?', r: item.reference }),
      note,
      fields: [
        {
          label: t('ci.rm_wd_field', {
            defaultValue: 'Why is it being withdrawn? — it stays on the record with your reason',
          }),
          value: typed,
          placeholder: t('ci.rm_wd_ph', {
            defaultValue: 'raised against the wrong job — reissued as REG-RFQ-25406-0007',
          }),
          multiline: true,
        },
      ],
      okLabel: t('ci.rm_wd_ok', { defaultValue: 'Withdraw it, with the reason' }),
      danger: true,
    });
    if (answers === null) return null; // cancelled
    typed = answers[0] ?? '';
    const reason = typed.trim();
    if (!reason) {
      // Empty is not a refusal to re-ask about, it is a non-answer. Say so
      // once and keep the dialog open rather than silently doing nothing.
      note = t('ci.rm_wd_need', {
        defaultValue: 'A reason is required — it is what the withdrawal is recorded as.',
      });
      continue;
    }
    try {
      await withdrawItem(item.id, reason);
      addToast({
        type: 'success',
        title: t('ci.rm_withdrawn', { defaultValue: '{{r}} withdrawn', r: item.reference }),
      });
      invalidate(ctx, item.id);
      return 'withdrawn';
    } catch (e) {
      const detail = errorDetail<{ error?: string; reason_rejected?: boolean }>(e);
      const msg = detail?.error?.trim() || (e as Error).message;
      const status = (e as { status?: number } | undefined)?.status;
      // A REFUSED REASON is re-asked; anything else (gone, forbidden, the
      // network) is a real failure and looping on it would trap the user
      // in a dialog that can never succeed.
      if (status === 400 || status === 422 || detail?.reason_rejected) {
        note = msg;
        continue;
      }
      addToast({ type: 'error', title: msg });
      return null;
    }
  }
}

/**
 * "Remove — raised in error…": confirm, delete, and turn the server's
 * refusal into the withdraw dialog rather than an error toast.
 */
export async function removeItemFlow(item: RemovableItem, ctx: RemoveCtx): Promise<RemoveOutcome> {
  const { t, addToast } = ctx;
  // Naming the reference in the question is the whole guard: the menu is
  // opened by right-clicking a row, and rows are one line apart.
  const sure = await qConfirm(
    t('ci.rm_del_title', { defaultValue: 'Remove {{r}} — raised in error?', r: item.reference }),
    t('ci.rm_del_note', {
      defaultValue:
        'If nothing has gone out on it, it is deleted outright and cannot be brought back. If it has already been emailed, you will be asked to withdraw it instead — with a reason, kept on the record.',
    }),
    t('ci.rm_del_ok', { defaultValue: 'Remove it' }),
    true,
  );
  if (!sure) return null;

  try {
    await deleteItem(item.id);
    addToast({
      type: 'success',
      title: t('ci.rm_deleted', { defaultValue: '{{r}} deleted', r: item.reference }),
    });
    invalidate(ctx, item.id);
    ctx.onGone?.(item.id);
    return 'deleted';
  } catch (e) {
    const refusal = removeRefusal(e);
    if (!refusal) {
      addToast({ type: 'error', title: (e as Error).message });
      return null;
    }
    // THE HANDOFF. Not "409 Conflict" in a red toast - the reasons the
    // server gave become the note above the reason field.
    return withdrawFlow(item, ctx, refusal);
  }
}

// ---------------------------------------------------------------------------
// The menu entries, and how a withdrawn row reads
// ---------------------------------------------------------------------------

/**
 * The remove entries for the register row's menu, separator included.
 * Nothing is offered on an item that is already withdrawn - there is
 * nothing left to remove, so it shows what happened to it instead.
 */
export function removeMenuItems(item: RegisterItemRow, ctx: RemoveCtx): (MenuItem | null)[] {
  const { t } = ctx;
  if (isWithdrawn(item)) {
    return [
      null,
      {
        label: t('ci.rm_already', { defaultValue: '⊘ Withdrawn' }),
        note: (item.withdrawn_at ?? '').slice(0, 10) || undefined,
        disabled: true,
        onClick: () => {},
      },
    ];
  }
  return [
    null,
    {
      label: t('ci.rm_menu', { defaultValue: '🗑 Remove — raised in error…' }),
      note: t('ci.rm_menu_note', { defaultValue: 'delete, or withdraw' }),
      danger: true,
      onClick: () => void removeItemFlow(item, ctx),
    },
    // Discoverable WITHOUT hitting the refusal first: once anything has
    // gone out, delete is never the answer, so name the action that is.
    wasEmailed(item)
      ? {
          label: t('ci.rm_wd_menu', { defaultValue: '⊘ Withdraw…' }),
          note: t('ci.rm_wd_menu_note', { defaultValue: 'stays on the record' }),
          danger: true,
          onClick: () => void withdrawFlow(item, ctx),
        }
      : null,
  ];
}

/** The struck-through, faded look of a row that has been pulled. */
export function withdrawnRowStyle(item: RemovableItem): CSSProperties | undefined {
  return isWithdrawn(item)
    ? { opacity: 0.5, textDecoration: 'line-through', textDecorationThickness: 1 }
    : undefined;
}

/** The `title` a disabled action carries, so the greying explains itself. */
export function withdrawnTitle(item: RemovableItem, t: TFunction): string | undefined {
  return isWithdrawn(item)
    ? t('ci.rm_disabled', {
        defaultValue: '{{r}} was withdrawn — {{why}}',
        r: item.reference,
        why: (item.withdrawn_reason ?? '').trim() || t('ci.rm_no_reason', { defaultValue: 'raised in error' }),
      })
    : undefined;
}

/** The banner on the expanded card: when, who, and why. */
export function WithdrawnBanner({ item, t }: { item: RemovableItem; t: TFunction }) {
  if (!isWithdrawn(item)) return null;
  return (
    <div
      className="pcard"
      data-testid="withdrawn-banner"
      style={{ borderLeftColor: 'var(--red, #b3261e)', padding: '8px 10px', marginBottom: 8 }}
    >
      <span className="badge b-red">{t('ci.rm_badge', { defaultValue: 'withdrawn' })}</span>{' '}
      <span style={{ whiteSpace: 'pre-wrap' }}>{withdrawnNote(item, t)}</span>
      <div className="v" style={{ marginTop: 4 }}>
        {t('ci.rm_banner_hint', {
          defaultValue:
            'It stays here as a record. It is out of the open lists and out of tracking, and nothing further can be sent on it.',
        })}
      </div>
    </div>
  );
}
