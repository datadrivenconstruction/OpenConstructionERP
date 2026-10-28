// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Closure stepper for a punch item.
 *
 * Shows the full lifecycle FSM (open -> assigned -> in_progress -> resolved ->
 * verified -> closed) as a horizontal stepper with the current stage
 * highlighted, and offers exactly the moves the backend will accept from the
 * current status (forward actions as primary buttons, reopen / unassign as
 * secondary ones). Every action calls the parent's transition handler, which is
 * wired to transitionPunchStatus. An optional note rides along with the next
 * status change (stored as the resolution note, or the reopen reason).
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  CheckCircle2,
  CircleDot,
  Loader2,
  Play,
  RotateCcw,
  ShieldCheck,
  StickyNote,
  UserCheck,
  UserMinus,
  Wrench,
  XCircle,
} from 'lucide-react';
import clsx from 'clsx';
import { Button } from '@/shared/ui';
import type { PunchItem, PunchStatus } from './api';
import { PUNCH_STAGES, punchNextMoves, punchStageIndex } from './punchlistFsm';

interface StageMeta {
  icon: React.ElementType;
  labelKey: string;
  defaultLabel: string;
}

const STAGE_META: Record<PunchStatus, StageMeta> = {
  open: { icon: CircleDot, labelKey: 'punch.status_open', defaultLabel: 'Open' },
  assigned: { icon: UserCheck, labelKey: 'punch.status_assigned', defaultLabel: 'Assigned' },
  in_progress: { icon: Play, labelKey: 'punch.status_in_progress', defaultLabel: 'In Progress' },
  resolved: { icon: Wrench, labelKey: 'punch.status_resolved', defaultLabel: 'Resolved' },
  verified: { icon: ShieldCheck, labelKey: 'punch.status_verified', defaultLabel: 'Verified' },
  closed: { icon: CheckCircle2, labelKey: 'punch.status_closed', defaultLabel: 'Closed' },
};

interface ActionMeta {
  icon: React.ElementType;
  labelKey: string;
  defaultLabel: string;
}

/** Resolve the action button label/icon for a move, refining the reopen path. */
function actionMeta(from: PunchStatus, to: PunchStatus): ActionMeta {
  if (to === 'open') {
    return from === 'assigned'
      ? { icon: UserMinus, labelKey: 'punch.action_unassign', defaultLabel: 'Unassign' }
      : { icon: RotateCcw, labelKey: 'punch.action_reopen', defaultLabel: 'Reopen' };
  }
  switch (to) {
    case 'assigned':
      return { icon: UserCheck, labelKey: 'punch.action_assign', defaultLabel: 'Assign' };
    case 'in_progress':
      return { icon: Play, labelKey: 'punch.action_start', defaultLabel: 'Start Work' };
    case 'resolved':
      return { icon: Wrench, labelKey: 'punch.action_resolve', defaultLabel: 'Mark Resolved' };
    case 'verified':
      return { icon: ShieldCheck, labelKey: 'punch.action_verify', defaultLabel: 'Verify' };
    case 'closed':
      return { icon: CheckCircle2, labelKey: 'punch.action_close', defaultLabel: 'Close' };
    default:
      return { icon: XCircle, labelKey: 'punch.action_move', defaultLabel: 'Move' };
  }
}

export function PunchClosureStepper({
  item,
  isPending,
  onTransition,
}: {
  item: PunchItem;
  isPending: boolean;
  /** Apply a status transition; `notes` is stored server-side when present. */
  onTransition: (next: PunchStatus, notes?: string) => void;
}) {
  const { t } = useTranslation();
  const current = item.status;
  const currentIndex = punchStageIndex(current);
  const { forward, backward } = punchNextMoves(current);

  const [note, setNote] = useState('');
  const [showNote, setShowNote] = useState(false);

  // Reset the note whenever the item's status changes (a move landed) so the
  // note does not silently ride along with the next, unrelated transition.
  useEffect(() => {
    setNote('');
    setShowNote(false);
  }, [item.status, item.id]);

  const apply = (next: PunchStatus) => onTransition(next, note);

  // Verify is gated server-side (four-eyes: a different user than the resolver,
  // plus the verify permission). Surface that up front rather than as a
  // surprise 400 after the click.
  const showVerifyHint = forward.includes('verified') || current === 'resolved';

  return (
    <div>
      <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
        {t('punch.lifecycle', { defaultValue: 'Status lifecycle' })}
      </h4>

      {/* ── Stepper rail ─────────────────────────────────────────────── */}
      <ol className="flex items-start justify-between gap-1" aria-label={t('punch.lifecycle', { defaultValue: 'Status lifecycle' })}>
        {PUNCH_STAGES.map((stage, idx) => {
          const meta = STAGE_META[stage];
          const Icon = meta.icon;
          const done = idx < currentIndex;
          const active = idx === currentIndex;
          const label = t(meta.labelKey, { defaultValue: meta.defaultLabel });
          return (
            <li key={stage} className="flex min-w-0 flex-1 flex-col items-center">
              <div className="flex w-full items-center">
                {/* Left connector (hidden on first node). */}
                <span
                  aria-hidden="true"
                  className={clsx(
                    'h-0.5 flex-1',
                    idx === 0 ? 'opacity-0' : done || active ? 'bg-oe-blue' : 'bg-border-light',
                  )}
                />
                <span
                  className={clsx(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 transition-colors',
                    done && 'border-oe-blue bg-oe-blue text-white',
                    active && 'border-oe-blue bg-oe-blue/10 text-oe-blue ring-2 ring-oe-blue/25',
                    !done && !active && 'border-border bg-surface-primary text-content-quaternary',
                  )}
                  aria-current={active ? 'step' : undefined}
                >
                  {done ? <Check size={14} /> : <Icon size={14} />}
                </span>
                {/* Right connector (hidden on last node). */}
                <span
                  aria-hidden="true"
                  className={clsx(
                    'h-0.5 flex-1',
                    idx === PUNCH_STAGES.length - 1 ? 'opacity-0' : done ? 'bg-oe-blue' : 'bg-border-light',
                  )}
                />
              </div>
              <span
                className={clsx(
                  'mt-1.5 truncate text-center text-2xs',
                  active ? 'font-semibold text-content-primary' : 'text-content-tertiary',
                )}
                title={label}
              >
                {label}
              </span>
            </li>
          );
        })}
      </ol>

      {/* ── Note (optional) ──────────────────────────────────────────── */}
      <div className="mt-4">
        {showNote ? (
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            autoFocus
            placeholder={t('punch.transition_note_placeholder', {
              defaultValue: 'Optional note added to the next status change (e.g. what was fixed, or why it is being reopened)',
            })}
            className="w-full resize-none rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        ) : (
          <button
            type="button"
            onClick={() => setShowNote(true)}
            className="inline-flex items-center gap-1.5 rounded-md text-xs text-content-tertiary hover:text-content-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            <StickyNote size={13} />
            {t('punch.add_transition_note', { defaultValue: 'Add a note (optional)' })}
          </button>
        )}
      </div>

      {/* ── Actions ──────────────────────────────────────────────────── */}
      {forward.length === 0 && backward.length === 0 ? (
        <p className="mt-3 text-xs text-content-tertiary">
          {t('punch.no_transitions', { defaultValue: 'No further status changes are available.' })}
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {forward.map((next) => {
            const meta = actionMeta(current, next);
            const Icon = meta.icon;
            return (
              <Button
                key={next}
                variant="primary"
                size="sm"
                onClick={() => apply(next)}
                disabled={isPending}
                icon={isPending ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
              >
                {t(meta.labelKey, { defaultValue: meta.defaultLabel })}
              </Button>
            );
          })}
          {backward.map((next) => {
            const meta = actionMeta(current, next);
            const Icon = meta.icon;
            return (
              <Button
                key={next}
                variant="ghost"
                size="sm"
                onClick={() => apply(next)}
                disabled={isPending}
                icon={<Icon size={14} />}
              >
                {t(meta.labelKey, { defaultValue: meta.defaultLabel })}
              </Button>
            );
          })}
        </div>
      )}

      {showVerifyHint && (
        <p className="mt-2 text-2xs text-content-quaternary">
          {t('punch.verify_hint', {
            defaultValue: 'Verification must be done by a different user than the one who resolved the item.',
          })}
        </p>
      )}
    </div>
  );
}
