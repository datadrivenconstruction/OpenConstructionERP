// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Shows the unlock celebration for every unlock the learner has not seen yet,
// one at a time, in course order. Mounted by TrainerSlot only while a course
// is active.
//
// On close the unlock is marked celebrated in the UI store at once (so it is
// never shown twice in this session) and `seen` is POSTed. The POST is
// idempotent and flips `seen` in the `/me` cache before it is sent. If it
// fails, the refetched `/me` still says `seen: false`; the host then posts
// again once on that next load, and stops there, so a server that keeps
// failing does not turn into a request loop.

import { useEffect, useMemo, useRef } from 'react';

import { courseLocaleOf } from './courseLocale';
import { getLock, isBadgeLockId } from './lockRegistry';
import { openingTaskFor, taskHref } from './LockedModulePage';
import { useMarkUnlockSeen } from './queries';
import type { TrainerMe, UnlockInfo } from './types';
import { UnlockModal, type UnlockModalProps } from './UnlockModal';
import { useTrainerUiStore } from './useTrainerUiStore';

/** At most this many `seen` POSTs per unlock while the host is mounted. */
const MAX_SEEN_POSTS = 2;

/** Open unlocks the learner has not seen, in course order. */
export function unseenUnlocks(me: Pick<TrainerMe, 'unlocks'>): UnlockInfo[] {
  return me.unlocks
    .filter((u) => u.state === 'open' && !u.seen)
    .sort((a, b) => a.opened_by_task - b.opened_by_task);
}

/** A static route of a registered lock (no `:param`), or null. */
function staticRouteOf(lockId: string): string | null {
  return getLock(lockId)?.routes.find((route) => !route.includes(':')) ?? null;
}

/**
 * Everything the modal needs for one unlock, or null when the course gives
 * it nothing to call it by (then there is nothing to celebrate on screen).
 */
export function unlockModalPropsFor(
  me: TrainerMe,
  unlock: UnlockInfo,
): Omit<UnlockModalProps, 'onClose'> | null {
  const opening = openingTaskFor(me, unlock.lock_id);
  const isBadge = unlock.kind === 'badge' || isBadgeLockId(unlock.lock_id);
  const label = (isBadge ? me.course.badge?.title : null) || opening?.opens_label || null;
  if (!label) return null;

  const nextTask = isBadge ? null : me.tasks.find((task) => task.n === unlock.opened_by_task + 1);
  const nextHref = nextTask && nextTask.status !== 'locked' ? taskHref(nextTask) : null;

  let goThere: string | null = null;
  if (!isBadge) {
    const lock = getLock(unlock.lock_id);
    if (lock?.kind === 'panel' && lock.panelAnchor && opening?.target) {
      goThere = `${opening.target.route.split('#', 1)[0]}#${lock.panelAnchor}`;
    } else {
      goThere = staticRouteOf(unlock.lock_id);
    }
  }

  return {
    unlock: {
      lockId: unlock.lock_id,
      kind: isBadge ? 'badge' : unlock.kind,
      label,
      openedByTask: unlock.opened_by_task,
      tiles: unlock.tiles,
    },
    contentLang: courseLocaleOf(me.course),
    progress: { done: me.progress.done, total: me.progress.total },
    rings: opening?.rings ?? null,
    week: me.week ? { done: me.week.done, goal: me.week.goal } : null,
    next: nextTask && nextHref ? { n: nextTask.n, taskId: nextTask.id, to: nextHref } : null,
    goThere,
  };
}

export interface UnlockHostProps {
  /** The active enrolment, from `useTrainerMode()` (decision 33). */
  me: TrainerMe;
}

export function UnlockHost({ me }: UnlockHostProps) {
  const celebrated = useTrainerUiStore((s) => s.celebrated);
  const markCelebrated = useTrainerUiStore((s) => s.markCelebrated);
  const { mutate: postSeen } = useMarkUnlockSeen();

  // Per unlock: how many POSTs went out, and for which `/me` snapshot.
  const posts = useRef(new Map<string, { count: number; me: TrainerMe }>());

  const unseen = useMemo(() => unseenUnlocks(me), [me]);
  const current = useMemo(() => {
    for (const unlock of unseen) {
      if (celebrated.includes(unlock.lock_id)) continue;
      const props = unlockModalPropsFor(me, unlock);
      if (props) return { unlock, props };
    }
    return null;
  }, [me, unseen, celebrated]);

  const send = (lockId: string) => {
    const prev = posts.current.get(lockId);
    if (prev && (prev.me === me || prev.count >= MAX_SEEN_POSTS)) return;
    posts.current.set(lockId, { count: (prev?.count ?? 0) + 1, me });
    postSeen(lockId);
  };

  // Retry: celebrated here, but the server still says unseen.
  useEffect(() => {
    for (const unlock of unseen) {
      if (celebrated.includes(unlock.lock_id)) send(unlock.lock_id);
    }
    // `send` reads the latest `me` through the closure of this render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unseen, celebrated]);

  if (!current) return null;
  const lockId = current.unlock.lock_id;
  return (
    <UnlockModal
      key={lockId}
      {...current.props}
      onClose={() => {
        // Count the POST before the store update re-renders the retry effect.
        send(lockId);
        markCelebrated(lockId);
      }}
    />
  );
}
