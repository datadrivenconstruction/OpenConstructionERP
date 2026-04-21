/**
 * TimelineScrubber — 4D playback strip for the BIM viewer.
 *
 * Rendered at the bottom of the viewer when `colorByMode === '4d_schedule'`
 * and the project has a usable schedule.  Layout:
 *
 *   [▶ / ⏸]  ━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━  [speed ▾]
 *            2026-01-01 │ 2026-03-15 │ 2026-06-01
 *            "Concrete pour — level 3"
 *
 * The handle is draggable (mouse + touch + keyboard).  `onChange` fires
 * debounced at 100 ms during drag and immediately on drop so the 3D
 * recolour keeps up without overwhelming the renderer.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Play, Pause, Calendar } from 'lucide-react';
import type { FourDTimelinePlaybackSpeed } from './use4dTimeline';

export interface TimelineScrubberProps {
  /** Schedule start, in UTC ms. */
  startMs: number;
  /** Schedule end, in UTC ms. */
  endMs: number;
  /** Current cursor position, in UTC ms. */
  currentMs: number;
  /** Fired on cursor change.  Debounced at 100 ms during drag, immediate
   *  on pointer-up / keyboard keys. */
  onChange: (ms: number) => void;
  /** Play-state; the button swaps Play ↔ Pause icons. */
  playing: boolean;
  /** Fired when the user hits the play/pause button. */
  onPlayToggle: () => void;
  /** Current speed multiplier. */
  speed: FourDTimelinePlaybackSpeed;
  onSpeedChange: (s: FourDTimelinePlaybackSpeed) => void;
  /** Label under the scrubber — which activity is "active" at currentMs. */
  activeActivity: string | null;
}

/** Format a UTC timestamp as `YYYY-MM-DD` — locale-independent so two
 *  users in different timezones see the same date under the same cursor. */
function fmtDate(ms: number): string {
  if (!Number.isFinite(ms)) return '—';
  const d = new Date(ms);
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

const SPEEDS: readonly FourDTimelinePlaybackSpeed[] = [1, 4, 16];

export function TimelineScrubber({
  startMs,
  endMs,
  currentMs,
  onChange,
  playing,
  onPlayToggle,
  speed,
  onSpeedChange,
  activeActivity,
}: TimelineScrubberProps) {
  const { t } = useTranslation();
  const railRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  /** The fraction of the rail the handle sits at, 0 at start, 1 at end. */
  const progress = useMemo(() => {
    const span = endMs - startMs;
    if (span <= 0) return 0;
    return Math.max(0, Math.min(1, (currentMs - startMs) / span));
  }, [currentMs, startMs, endMs]);

  const midMs = startMs + (endMs - startMs) * 0.5;
  const quarterMs = startMs + (endMs - startMs) * 0.25;
  const threeQuarterMs = startMs + (endMs - startMs) * 0.75;

  /* ── Debounced onChange ───────────────────────────────────────────
   * During drag we want a smooth visual response (the handle follows
   * the pointer frame-by-frame) but we don't want to trigger a full
   * recolour on every pointermove event — that would cost us ~10 ms
   * per frame on big models.  So we throttle the parent-facing
   * `onChange` to once per 100 ms while dragging, then flush on
   * drop so the final state is guaranteed exact. */
  const lastEmitRef = useRef<number>(0);
  const pendingMsRef = useRef<number | null>(null);
  const flushTimerRef = useRef<number | null>(null);

  const emit = useCallback(
    (ms: number, immediate: boolean) => {
      if (immediate) {
        if (flushTimerRef.current != null) {
          window.clearTimeout(flushTimerRef.current);
          flushTimerRef.current = null;
        }
        pendingMsRef.current = null;
        lastEmitRef.current = Date.now();
        onChange(ms);
        return;
      }
      const now = Date.now();
      pendingMsRef.current = ms;
      if (now - lastEmitRef.current >= 100) {
        lastEmitRef.current = now;
        const latest = pendingMsRef.current;
        pendingMsRef.current = null;
        onChange(latest);
      } else if (flushTimerRef.current == null) {
        flushTimerRef.current = window.setTimeout(() => {
          flushTimerRef.current = null;
          const latest = pendingMsRef.current;
          if (latest != null) {
            pendingMsRef.current = null;
            lastEmitRef.current = Date.now();
            onChange(latest);
          }
        }, 100);
      }
    },
    [onChange],
  );

  useEffect(() => {
    // Clean up any pending timer when the component unmounts so we
    // don't emit to a stale onChange.
    return () => {
      if (flushTimerRef.current != null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, []);

  /** Compute the schedule timestamp for a pointer x inside the rail's
   *  bounding rect.  Clamped to [startMs, endMs] so extreme drags
   *  outside the rail don't overshoot. */
  const pointerToMs = useCallback(
    (clientX: number): number => {
      const el = railRef.current;
      if (!el) return currentMs;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0) return currentMs;
      const frac = Math.max(
        0,
        Math.min(1, (clientX - rect.left) / rect.width),
      );
      return startMs + frac * (endMs - startMs);
    },
    [currentMs, startMs, endMs],
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      setDragging(true);
      const ms = pointerToMs(e.clientX);
      emit(ms, true);
    },
    [pointerToMs, emit],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging) return;
      const ms = pointerToMs(e.clientX);
      emit(ms, false);
    },
    [dragging, pointerToMs, emit],
  );

  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging) return;
      (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
      setDragging(false);
      const ms = pointerToMs(e.clientX);
      emit(ms, true);
    },
    [dragging, pointerToMs, emit],
  );

  /** Keyboard — Left/Right arrow jumps 1% of the span; Home/End snaps
   *  to the extremes.  Makes the scrubber accessible to keyboard users
   *  as required by WCAG 2.1 for slider widgets. */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      const span = endMs - startMs;
      if (span <= 0) return;
      const step = span * 0.01;
      let next = currentMs;
      if (e.key === 'ArrowLeft') next = currentMs - step;
      else if (e.key === 'ArrowRight') next = currentMs + step;
      else if (e.key === 'Home') next = startMs;
      else if (e.key === 'End') next = endMs;
      else if (e.key === ' ') {
        e.preventDefault();
        onPlayToggle();
        return;
      } else return;
      e.preventDefault();
      emit(Math.max(startMs, Math.min(endMs, next)), true);
    },
    [currentMs, startMs, endMs, emit, onPlayToggle],
  );

  return (
    <div
      className="absolute bottom-3 start-1/2 -translate-x-1/2 z-20 w-[min(720px,calc(100%-24px))] rounded-xl bg-surface-primary border border-border-light shadow-lg px-4 py-3 flex flex-col gap-2"
      data-testid="bim-4d-scrubber"
      role="group"
      aria-label={t('bim.4d_scrubber_label', { defaultValue: '4D timeline scrubber' })}
      onClick={(e) => e.stopPropagation()}
    >
      {/* Top row: play button · rail · speed selector */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onPlayToggle}
          className="shrink-0 inline-flex items-center justify-center h-8 w-8 rounded-full bg-oe-blue text-white hover:bg-oe-blue/90 transition-colors"
          aria-label={
            playing
              ? t('bim.4d_pause', { defaultValue: 'Pause' })
              : t('bim.4d_play', { defaultValue: 'Play' })
          }
          data-testid="bim-4d-play"
        >
          {playing ? <Pause size={14} /> : <Play size={14} className="ms-0.5" />}
        </button>

        <div
          ref={railRef}
          className="relative flex-1 h-2 rounded-full bg-surface-tertiary cursor-pointer touch-none select-none"
          role="slider"
          tabIndex={0}
          aria-valuemin={startMs}
          aria-valuemax={endMs}
          aria-valuenow={currentMs}
          aria-valuetext={fmtDate(currentMs)}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onKeyDown={handleKeyDown}
          data-testid="bim-4d-rail"
        >
          {/* Progress fill */}
          <div
            className="absolute inset-y-0 start-0 rounded-full bg-oe-blue/60 pointer-events-none"
            style={{ width: `${progress * 100}%` }}
          />
          {/* Quarter tick marks */}
          {[0.25, 0.5, 0.75].map((frac) => (
            <span
              key={frac}
              className="absolute top-1/2 -translate-y-1/2 h-2 w-px bg-border-medium opacity-60 pointer-events-none"
              style={{ left: `${frac * 100}%` }}
            />
          ))}
          {/* Handle */}
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-4 w-4 rounded-full bg-white border-2 border-oe-blue shadow-sm pointer-events-none"
            style={{ left: `${progress * 100}%` }}
            data-testid="bim-4d-handle"
          />
        </div>

        <select
          value={speed}
          onChange={(e) => {
            const v = Number(e.target.value) as FourDTimelinePlaybackSpeed;
            if (SPEEDS.includes(v)) onSpeedChange(v);
          }}
          className="shrink-0 text-[11px] py-1 px-1.5 rounded border border-border-light bg-surface-secondary text-content-secondary hover:bg-surface-tertiary focus:outline-none focus:ring-1 focus:ring-oe-blue"
          aria-label={t('bim.4d_speed', { defaultValue: 'Playback speed' })}
          data-testid="bim-4d-speed"
        >
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
      </div>

      {/* Date tick labels — render at 25% / 50% / 75% so users orient
          without cluttering the rail itself. */}
      <div className="relative h-3 text-[9px] text-content-tertiary tabular-nums select-none">
        <span
          className="absolute -translate-x-1/2"
          style={{ left: '25%' }}
          aria-hidden="true"
        >
          {fmtDate(quarterMs)}
        </span>
        <span
          className="absolute -translate-x-1/2"
          style={{ left: '50%' }}
          aria-hidden="true"
        >
          {fmtDate(midMs)}
        </span>
        <span
          className="absolute -translate-x-1/2"
          style={{ left: '75%' }}
          aria-hidden="true"
        >
          {fmtDate(threeQuarterMs)}
        </span>
      </div>

      {/* Current date + active activity name */}
      <div className="flex items-center justify-between gap-3 text-[11px]">
        <span
          className="inline-flex items-center gap-1 text-content-primary font-medium tabular-nums"
          data-testid="bim-4d-current-date"
        >
          <Calendar size={11} className="text-oe-blue" />
          {fmtDate(currentMs)}
        </span>
        <span
          className="text-content-secondary truncate ms-2"
          title={activeActivity ?? undefined}
          data-testid="bim-4d-active-activity"
        >
          {activeActivity ??
            t('bim.4d_no_activity', { defaultValue: 'No activity at this date' })}
        </span>
      </div>
    </div>
  );
}
