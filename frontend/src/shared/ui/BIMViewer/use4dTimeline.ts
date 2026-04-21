/**
 * use4dTimeline — React hook that powers the 4D timeline scrubber.
 *
 * Responsibilities:
 *   · Fetch every schedule + activity for a project (using existing
 *     /v1/schedule endpoints).
 *   · Compute [startDate, endDate] from the union of activity windows.
 *   · Expose a playable `currentDate` cursor with play / pause / speed.
 *   · Build a fast `elementId → activityId[]` map from the
 *     `activity.bim_element_ids` arrays so callers can hand off to
 *     `resolveElementStatus` without scanning the activity list per-element.
 *   · Track the "currently active" activity label at `currentDate`.
 *   · Fail silently — when the project has no schedule / no activities
 *     the hook returns `{ isAvailable: false }` so the viewer can hide
 *     the scrubber without any error handling.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import {
  computeScheduleBounds,
  pickActiveActivityName,
  type FourDActivity,
} from './4dStatus';

/** Response shape for `/v1/schedule/schedules/?project_id=...`.  We only
 *  need the id, but keep the full shape loose so casual changes on the
 *  backend don't break the frontend build. */
interface ScheduleSummary {
  id: string;
  project_id: string;
  name?: string;
  start_date?: string | null;
  end_date?: string | null;
}

/** Response shape for `/v1/schedule/schedules/{id}/activities/`. */
interface ScheduleActivity extends FourDActivity {
  id: string;
  schedule_id?: string;
  name: string;
  start_date: string | null;
  end_date: string | null;
  bim_element_ids?: string[] | null;
}

export type FourDTimelinePlaybackSpeed = 1 | 4 | 16;

export interface Use4dTimelineResult {
  /** `true` when the project has a schedule with at least one date-ed
   *  activity.  When `false`, the scrubber is hidden. */
  isAvailable: boolean;
  /** Schedule start, in UTC ms (earliest activity start). */
  startMs: number;
  /** Schedule end, in UTC ms (latest activity end). */
  endMs: number;
  /** Current cursor position, in UTC ms. */
  currentMs: number;
  /** Move the cursor.  Clamped to [startMs, endMs]. */
  setCurrentMs: (ms: number) => void;
  /** Currently playing? */
  playing: boolean;
  /** Toggle play / pause. */
  togglePlay: () => void;
  /** Playback speed multiplier. 1× = real-time wall-clock day per second
   *  is too slow for construction schedules, so defaults to 4×. */
  speed: FourDTimelinePlaybackSpeed;
  setSpeed: (s: FourDTimelinePlaybackSpeed) => void;
  /** Loaded activities (flattened across every schedule in the project). */
  activities: readonly FourDActivity[];
  /** Quick lookup: activity id → activity object. */
  activitiesById: ReadonlyMap<string, FourDActivity>;
  /** Inverted index: element id → activity ids that pin it. */
  elementToActivities: ReadonlyMap<string, readonly string[]>;
  /** Human-readable label of the activity most relevant at `currentMs`.
   *  `null` when the schedule is empty or the cursor is before/after
   *  every activity window. */
  activeActivityName: string | null;
}

/** When no schedule is available we still return an object of the same
 *  shape so the consumer doesn't have to null-check on every field.
 *  The viewer only renders the scrubber when `isAvailable === true`. */
const UNAVAILABLE: Use4dTimelineResult = {
  isAvailable: false,
  startMs: 0,
  endMs: 0,
  currentMs: 0,
  setCurrentMs: () => {
    /* noop */
  },
  playing: false,
  togglePlay: () => {
    /* noop */
  },
  speed: 4,
  setSpeed: () => {
    /* noop */
  },
  activities: [],
  activitiesById: new Map(),
  elementToActivities: new Map(),
  activeActivityName: null,
};

/** One real-time second of playback advances the cursor by `speed` days.
 *  At 4× this means a 180-day schedule plays through in 45 seconds — fast
 *  enough to be satisfying, slow enough to see transitions. */
const MS_PER_DAY = 86_400_000;

/** Fetch every schedule for the project in one batch, then fan out to
 *  fetch activities for each schedule.  Parallelised via `Promise.all`.
 *  Kept inside the hook file so module boundaries stay tidy — this is
 *  not a reusable fetch layer, it's specific to the 4D scrubber. */
async function fetchAllActivities(projectId: string): Promise<ScheduleActivity[]> {
  const schedules = await apiGet<ScheduleSummary[] | { items: ScheduleSummary[] }>(
    `/v1/schedule/schedules/?project_id=${encodeURIComponent(projectId)}`,
  );
  const schedList = Array.isArray(schedules) ? schedules : schedules.items ?? [];
  if (schedList.length === 0) return [];

  const results = await Promise.all(
    schedList.map(async (sched) => {
      try {
        const acts = await apiGet<
          ScheduleActivity[] | { items: ScheduleActivity[] }
        >(`/v1/schedule/schedules/${encodeURIComponent(sched.id)}/activities/`);
        return Array.isArray(acts) ? acts : acts.items ?? [];
      } catch {
        // Individual schedule failure is non-fatal — we may still have
        // actionable data in the other schedules.  Log at debug only to
        // avoid spamming the console for projects with many schedules.
        return [];
      }
    }),
  );
  return results.flat();
}

/**
 * Hook — fetches + manages state for the 4D scrubber.  Safe to call even
 * when the project has no schedule; returns `{ isAvailable: false }` in
 * that case so the caller can short-circuit.
 */
export function use4dTimeline(
  projectId: string | undefined,
  enabled: boolean,
): Use4dTimelineResult {
  const query = useQuery({
    queryKey: ['4d-timeline-activities', projectId],
    queryFn: () => (projectId ? fetchAllActivities(projectId) : Promise.resolve([])),
    enabled: !!projectId && enabled,
    staleTime: 60_000,
  });

  const activities = query.data ?? [];

  const activitiesById = useMemo(() => {
    const m = new Map<string, FourDActivity>();
    for (const a of activities) {
      m.set(a.id, {
        id: a.id,
        name: a.name,
        start_date: a.start_date ?? null,
        end_date: a.end_date ?? null,
      });
    }
    return m;
  }, [activities]);

  /** Build the inverted index: for every activity, every element id it
   *  pins gets an entry pointing back.  Stored as arrays because
   *  downstream `resolveElementStatus` iterates them. */
  const elementToActivities = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const a of activities) {
      const ids = a.bim_element_ids ?? [];
      for (const elId of ids) {
        const list = m.get(elId);
        if (list) list.push(a.id);
        else m.set(elId, [a.id]);
      }
    }
    return m as ReadonlyMap<string, readonly string[]>;
  }, [activities]);

  const bounds = useMemo(() => computeScheduleBounds(activities), [activities]);

  /** Schedule is "available" when we have ≥1 activity with BOTH a start
   *  and an end date — otherwise the scrubber has nothing meaningful to
   *  show.  Intentionally strict so partially-configured schedules don't
   *  render a bogus 1-hour window. */
  const isAvailable =
    bounds.startMs != null &&
    bounds.endMs != null &&
    bounds.endMs > bounds.startMs &&
    activities.length > 0;

  const startMs = bounds.startMs ?? 0;
  const endMs = bounds.endMs ?? 0;

  const [currentMs, _setCurrentMs] = useState<number>(startMs);

  // Re-anchor the cursor when the schedule bounds change (first fetch
  // completes, or the user switches to a different project).  Keeps the
  // scrubber from pointing to stale timestamps outside the new window.
  useEffect(() => {
    if (isAvailable) _setCurrentMs(startMs);
  }, [isAvailable, startMs]);

  const setCurrentMs = useCallback(
    (ms: number) => {
      if (!isAvailable) return;
      const clamped = Math.max(startMs, Math.min(endMs, ms));
      _setCurrentMs(clamped);
    },
    [isAvailable, startMs, endMs],
  );

  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<FourDTimelinePlaybackSpeed>(4);

  const togglePlay = useCallback(() => {
    if (!isAvailable) return;
    setPlaying((p) => {
      // If the user hits play after the cursor already reached the end,
      // auto-rewind to the start so they can watch it again without an
      // extra scrub.
      if (!p && currentMs >= endMs) _setCurrentMs(startMs);
      return !p;
    });
  }, [isAvailable, currentMs, endMs, startMs]);

  /* ── Play loop (requestAnimationFrame) ─────────────────────────────
   * Advances the cursor by `speed × realDeltaDays` every frame.  At 4×
   * speed, one wall-clock second of playback covers 4 schedule days.
   * We stop and clear `playing` automatically when we hit `endMs` so
   * the button's icon swaps back to "play" without the consumer having
   * to watch for it. */
  const rafRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);
  const currentMsRef = useRef(currentMs);
  useEffect(() => {
    currentMsRef.current = currentMs;
  }, [currentMs]);

  useEffect(() => {
    if (!playing || !isAvailable) {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      lastFrameRef.current = null;
      return;
    }

    const step = (now: number) => {
      const last = lastFrameRef.current;
      lastFrameRef.current = now;
      if (last == null) {
        rafRef.current = requestAnimationFrame(step);
        return;
      }
      const realDeltaMs = now - last;
      const scheduleAdvance = (realDeltaMs / 1000) * speed * MS_PER_DAY;
      const next = currentMsRef.current + scheduleAdvance;
      if (next >= endMs) {
        _setCurrentMs(endMs);
        setPlaying(false);
        return;
      }
      _setCurrentMs(next);
      rafRef.current = requestAnimationFrame(step);
    };

    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      lastFrameRef.current = null;
    };
  }, [playing, isAvailable, speed, endMs]);

  const activeActivityName = useMemo(
    () => (isAvailable ? pickActiveActivityName(currentMs, activities) : null),
    [isAvailable, currentMs, activities],
  );

  if (!isAvailable) return UNAVAILABLE;

  return {
    isAvailable: true,
    startMs,
    endMs,
    currentMs,
    setCurrentMs,
    playing,
    togglePlay,
    speed,
    setSpeed,
    activities,
    activitiesById,
    elementToActivities,
    activeActivityName,
  };
}
