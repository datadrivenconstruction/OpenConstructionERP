// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure math for the on-screen walk joystick (touch site mode).
 *
 * Converts a pointer position relative to the joystick base centre into a
 * normalized movement vector for `WalkMode.setMoveAxis`, plus the clamped
 * knob offset for rendering. Kept pure and side-effect-free so it is unit
 * testable without a DOM (matches measureMath / geoLocate).
 *
 * Screen coordinates grow downward, so pushing the stick UP (negative dy)
 * maps to positive `forward`. The vector is clamped to the unit circle so a
 * diagonal push can never exceed full speed, and a small deadzone near the
 * centre is ignored so a resting thumb does not creep the camera.
 */

/** Result of {@link joystickVector}. */
export interface JoystickReading {
  /** Left/right movement axis, -1..1 (positive = right). */
  strafe: number;
  /** Forward/back movement axis, -1..1 (positive = forward / screen up). */
  forward: number;
  /** Post-deadzone magnitude, 0..1. Zero inside the deadzone. */
  magnitude: number;
  /** Knob X offset in px, clamped to the base radius (for rendering). */
  knobX: number;
  /** Knob Y offset in px, clamped to the base radius (for rendering). */
  knobY: number;
}

const ZERO: JoystickReading = { strafe: 0, forward: 0, magnitude: 0, knobX: 0, knobY: 0 };

export interface JoystickOptions {
  /** Fraction of the radius (0..1) ignored near the centre. Default 0.15. */
  deadzone?: number;
}

/**
 * @param dx     pointer X minus base-centre X, in px (right positive).
 * @param dy     pointer Y minus base-centre Y, in px (down positive).
 * @param radius joystick base radius in px (the knob travel limit).
 */
export function joystickVector(
  dx: number,
  dy: number,
  radius: number,
  opts: JoystickOptions = {},
): JoystickReading {
  if (!Number.isFinite(dx) || !Number.isFinite(dy) || !Number.isFinite(radius) || radius <= 0) {
    return ZERO;
  }
  const deadzone = Math.max(0, Math.min(0.9, opts.deadzone ?? 0.15));

  // Normalized distance from centre (1 == at the base edge).
  const nx = dx / radius;
  const ny = dy / radius;
  const dist = Math.hypot(nx, ny);

  // Knob position: follow the finger but never leave the base circle.
  const knobScale = dist > 1 ? 1 / dist : 1;
  const knobX = dx * knobScale;
  const knobY = dy * knobScale;

  if (dist <= deadzone) {
    return { strafe: 0, forward: 0, magnitude: 0, knobX, knobY };
  }

  // Clamp to the unit circle, then rescale deadzone..1 -> 0..1 so movement
  // ramps smoothly from just outside the deadzone to full speed at the edge.
  const clamped = Math.min(dist, 1);
  const magnitude = (clamped - deadzone) / (1 - deadzone);

  const ux = nx / dist;
  const uy = ny / dist;
  return {
    strafe: ux * magnitude,
    // Negate: screen-down (+y) is backward, screen-up (-y) is forward.
    forward: -uy * magnitude,
    magnitude,
    knobX,
    knobY,
  };
}
