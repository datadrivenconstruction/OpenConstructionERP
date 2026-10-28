// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * On-screen walk joystick for touch site mode.
 *
 * Walk-mode look already works on touch (drag to look), but locomotion was
 * keyboard-only. This thumb-stick fills that gap: drag the knob to drive the
 * camera. It is purely a thin DOM/pointer wrapper - all the vector math lives
 * in the pure, unit-tested {@link joystickVector} - and it reports a
 * normalized (-1..1) strafe/forward axis via `onMove`, which the viewer feeds
 * to `WalkMode.setMoveAxis`. On release it emits a zero vector so the camera
 * stops.
 *
 * The component is position-agnostic: the parent places it (e.g. bottom-start
 * of the viewport). `touch-action: none` stops the browser panning/zooming
 * the page while the thumb is on the stick.
 */
import { useCallback, useRef, useState } from 'react';

import { joystickVector } from './joystickVector';

const BASE_RADIUS = 56; // px; base diameter = 112
const KNOB_RADIUS = 26; // px; knob diameter = 52

export interface WalkJoystickProps {
  /** Normalized movement axis, each -1..1 (strafe: right+, forward: fwd+). */
  onMove: (strafe: number, forward: number) => void;
  /** Fired once when the thumb lifts (after a final zero `onMove`). */
  onEnd?: () => void;
  /** Accessible label for the control. */
  ariaLabel?: string;
}

export function WalkJoystick({ onMove, onEnd, ariaLabel }: WalkJoystickProps) {
  const baseRef = useRef<HTMLDivElement>(null);
  const centerRef = useRef<{ x: number; y: number } | null>(null);
  const [knob, setKnob] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [active, setActive] = useState(false);

  const apply = useCallback(
    (clientX: number, clientY: number) => {
      const c = centerRef.current;
      if (!c) return;
      const r = joystickVector(clientX - c.x, clientY - c.y, BASE_RADIUS);
      setKnob({ x: r.knobX, y: r.knobY });
      onMove(r.strafe, r.forward);
    },
    [onMove],
  );

  const handleDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const el = baseRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      centerRef.current = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      try {
        el.setPointerCapture(e.pointerId);
      } catch {
        /* capture unsupported in some environments - ignore */
      }
      setActive(true);
      apply(e.clientX, e.clientY);
      e.preventDefault();
    },
    [apply],
  );

  const handleMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!centerRef.current) return;
      apply(e.clientX, e.clientY);
      e.preventDefault();
    },
    [apply],
  );

  const end = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      centerRef.current = null;
      setActive(false);
      setKnob({ x: 0, y: 0 });
      onMove(0, 0);
      onEnd?.();
      try {
        baseRef.current?.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    },
    [onMove, onEnd],
  );

  return (
    <div
      ref={baseRef}
      role="button"
      aria-label={ariaLabel ?? 'Walk joystick'}
      onPointerDown={handleDown}
      onPointerMove={handleMove}
      onPointerUp={end}
      onPointerCancel={end}
      className="relative flex select-none items-center justify-center rounded-full border border-white/40 bg-black/25 shadow-lg backdrop-blur-sm"
      style={{ width: BASE_RADIUS * 2, height: BASE_RADIUS * 2, touchAction: 'none' }}
    >
      {/* Centre crosshair dot for orientation */}
      <div className="absolute h-1 w-1 rounded-full bg-white/40" />
      {/* Knob */}
      <div
        className={`absolute rounded-full border border-white/70 shadow transition-colors ${
          active ? 'bg-oe-blue' : 'bg-oe-blue/80'
        }`}
        style={{
          width: KNOB_RADIUS * 2,
          height: KNOB_RADIUS * 2,
          left: '50%',
          top: '50%',
          marginLeft: -KNOB_RADIUS,
          marginTop: -KNOB_RADIUS,
          transform: `translate(${knob.x}px, ${knob.y}px)`,
        }}
      />
    </div>
  );
}
