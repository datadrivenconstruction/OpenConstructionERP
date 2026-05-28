/**
 * WalkMode — first-person walk-through navigation built on
 * three.js `PointerLockControls`.
 *
 * Controls (mirrors BIMcollab / Navisworks walk mode):
 *   - mouse drag (while locked) → look
 *   - W/A/S/D / arrow keys      → walk
 *   - Q / PageDown / Ctrl       → down
 *   - E / Space / PageUp        → up
 *   - Shift                     → sprint (3× speed)
 *   - ESC                       → release pointer-lock (browser drives it),
 *                                 callers also listen for Escape on window
 *                                 to fully disable the tool.
 *
 * Speed: a velocity multiplier (metres / second) is exposed via
 * `setFlightSpeed`.  Default = 2 m/s; recommended UI range is
 * `bboxDiagonal / 50` … `bboxDiagonal / 5`, computed by the toolbar.
 *
 * Coexistence with OrbitControls: the caller is responsible for disabling
 * OrbitControls BEFORE calling `enable()`.  If `args.orbitControls` is
 * provided and `.enabled === true`, `enable()` throws — that flips a
 * bug we'd otherwise hit at runtime (camera fights between the two
 * controllers, tearing every frame).
 */

import * as THREE from 'three';
import { PointerLockControls } from 'three/examples/jsm/controls/PointerLockControls.js';

export interface WalkModeArgs {
  camera: THREE.Camera;
  renderer: THREE.WebGLRenderer;
  domElement: HTMLElement;
  /** Optional OrbitControls reference. If supplied, `enable()` checks that
   *  it has been disabled by the caller and throws if not. */
  orbitControls?: { enabled: boolean };
  /** Optional callback fired whenever the camera moved during a tick.
   *  The host wires this to `SceneManager.requestRender()` so the
   *  on-demand render loop redraws — without it the camera moves but the
   *  user sees no motion because OrbitControls (the only other source of
   *  render invalidation) is disabled in walk mode. */
  onChange?: () => void;
}

const DEFAULT_SPEED = 2; // m/s
const SPRINT_MULTIPLIER = 3;

export class WalkMode {
  private camera: THREE.Camera;
  // Renderer kept on the API for symmetry with SectionBox / MeasureTool;
  // WalkMode itself drives the PointerLockControls which holds its own
  // domElement reference. Underscored to silence noUnusedLocals.
  private _renderer: THREE.WebGLRenderer;
  private domElement: HTMLElement;
  private orbitControls?: { enabled: boolean };
  private onChange?: () => void;

  private controls: PointerLockControls | null = null;
  private _enabled = false;
  private _locked = false;
  private flightSpeed = DEFAULT_SPEED;
  /** Listeners notified when the pointer-lock state changes. Used by the
   *  React shell to render an on-screen "Mouse: look · WASD: move" hint
   *  only while the cursor is actually locked. */
  private lockListeners = new Set<(locked: boolean) => void>();

  /** Active WASD key state. Polled inside `tick()`. */
  private keys: Record<string, boolean> = {
    forward: false,
    backward: false,
    left: false,
    right: false,
    up: false,
    down: false,
    sprint: false,
  };

  private animId: number | null = null;
  private lastTickMs = 0;

  /** Bound listener references so removeEventListener can target them. */
  private onKeyDown = (e: KeyboardEvent): void => this.handleKey(e, true);
  private onKeyUp = (e: KeyboardEvent): void => this.handleKey(e, false);
  private onLock = (): void => {
    this._locked = true;
    for (const l of this.lockListeners) l(true);
  };
  private onUnlock = (): void => {
    this._locked = false;
    for (const l of this.lockListeners) l(false);
  };
  /** Re-acquire pointer lock on a user click after the browser dropped it
   *  (e.g. user hit Esc but stayed in walk mode, or the initial lock()
   *  call rejected because it lacked a user gesture). */
  private onClickReacquire = (): void => {
    if (!this._enabled || this._locked || !this.controls) return;
    try {
      this.controls.lock();
    } catch {
      /* still no user gesture; ignore */
    }
  };

  constructor(args: WalkModeArgs) {
    this.camera = args.camera;
    this._renderer = args.renderer;
    this.domElement = args.domElement;
    this.orbitControls = args.orbitControls;
    this.onChange = args.onChange;
    void this._renderer;
  }

  isEnabled(): boolean {
    return this._enabled;
  }

  isLocked(): boolean {
    return this._locked;
  }

  /** Subscribe to pointer-lock state. Returns an unsubscribe fn. The
   *  listener is called immediately with the current value so the UI
   *  can render in sync from the first paint. */
  onLockChange(listener: (locked: boolean) => void): () => void {
    this.lockListeners.add(listener);
    listener(this._locked);
    return () => {
      this.lockListeners.delete(listener);
    };
  }

  setFlightSpeed(speed: number): void {
    if (!Number.isFinite(speed) || speed <= 0) return;
    this.flightSpeed = speed;
  }

  getFlightSpeed(): number {
    return this.flightSpeed;
  }

  enable(): void {
    if (this._enabled) return;
    if (this.orbitControls && this.orbitControls.enabled) {
      throw new Error(
        'WalkMode.enable(): OrbitControls is still active — disable it first to avoid camera-fight rendering bugs.',
      );
    }
    this.controls = new PointerLockControls(this.camera, this.domElement);
    this._enabled = true;

    // `capture: true` ensures we intercept arrow/space/etc BEFORE they
    // bubble to any panel/sidebar that listens for them (which used to
    // make panels appear to move alongside the camera).
    window.addEventListener('keydown', this.onKeyDown, { capture: true });
    window.addEventListener('keyup', this.onKeyUp, { capture: true });
    this.controls.addEventListener('lock', this.onLock);
    this.controls.addEventListener('unlock', this.onUnlock);
    // Click on the canvas re-acquires pointer lock if the user dropped it
    // (Esc inside the browser releases the cursor without exiting walk
    // mode in our state machine).
    this.domElement.addEventListener('click', this.onClickReacquire);

    // Request pointer lock immediately so the user can start looking
    // without a second click. In jsdom this is a no-op stub. Browsers
    // require this call to be inside a user-gesture; the click that
    // toggled the toolbar button counts, so this usually succeeds.
    try {
      this.controls.lock();
    } catch {
      // Some browsers throw if called without a user gesture; the
      // canvas-click listener above will pick up the next click.
    }

    this.lastTickMs = typeof performance !== 'undefined' ? performance.now() : Date.now();
    this.startLoop();
  }

  disable(): void {
    if (!this._enabled) return;
    this._enabled = false;
    this.stopLoop();

    window.removeEventListener('keydown', this.onKeyDown, { capture: true });
    window.removeEventListener('keyup', this.onKeyUp, { capture: true });
    this.domElement.removeEventListener('click', this.onClickReacquire);

    if (this.controls) {
      try {
        this.controls.unlock();
      } catch {
        // Ignore — already unlocked or in test env without pointer lock.
      }
      this.controls.removeEventListener('lock', this.onLock);
      this.controls.removeEventListener('unlock', this.onUnlock);
      // Dispose if available (newer three.js exposes it).
      const c = this.controls as unknown as { dispose?: () => void };
      if (typeof c.dispose === 'function') c.dispose();
      this.controls = null;
    }
    if (this._locked) {
      this._locked = false;
      for (const l of this.lockListeners) l(false);
    }
    // Reset key state so a leftover key-up arriving after disable()
    // does not poison the next enable().
    for (const k of Object.keys(this.keys)) this.keys[k] = false;
  }

  dispose(): void {
    this.disable();
    this.lockListeners.clear();
  }

  /** Integrate the current WASD/space/shift state into the camera position.
   *  Exposed for tests; production code drives this from the internal RAF
   *  loop. `deltaSeconds` is clamped to a sane upper bound so a tab that
   *  was backgrounded does not teleport the camera on resume. */
  tick(deltaSeconds: number): void {
    if (!this._enabled || !this.controls) return;
    // Clamp to 1 s so a backgrounded tab doesn't teleport on resume, but
    // still permits half-second test ticks without scaling them down.
    const dt = Math.min(Math.max(deltaSeconds, 0), 1);
    if (dt === 0) return;
    const speed = this.keys.sprint ? this.flightSpeed * SPRINT_MULTIPLIER : this.flightSpeed;
    const distance = speed * dt;

    const moved =
      this.keys.forward ||
      this.keys.backward ||
      this.keys.left ||
      this.keys.right ||
      this.keys.up ||
      this.keys.down;

    // Forward/back/left/right are camera-relative; up/down are world-Y.
    if (this.keys.forward) this.controls.moveForward(distance);
    if (this.keys.backward) this.controls.moveForward(-distance);
    if (this.keys.right) this.controls.moveRight(distance);
    if (this.keys.left) this.controls.moveRight(-distance);
    if (this.keys.up) this.camera.position.y += distance;
    if (this.keys.down) this.camera.position.y -= distance;

    // While pointer-lock is active the user is also free-looking via mouse
    // (PointerLockControls mutates the camera quaternion directly without
    // notifying us), so we have to redraw every frame the cursor is
    // captured — not just frames where a key moved the position. The host
    // SceneManager is on-demand and would otherwise sit frozen while the
    // mouse moves.
    if (moved || this._locked) {
      this.onChange?.();
    }
  }

  private startLoop(): void {
    if (this.animId !== null) return;
    const step = (now: number): void => {
      if (!this._enabled) return;
      const dt = (now - this.lastTickMs) / 1000;
      this.lastTickMs = now;
      this.tick(dt);
      this.animId =
        typeof requestAnimationFrame === 'function'
          ? requestAnimationFrame(step)
          : null;
    };
    this.animId =
      typeof requestAnimationFrame === 'function'
        ? requestAnimationFrame(step)
        : null;
  }

  private stopLoop(): void {
    if (this.animId !== null && typeof cancelAnimationFrame === 'function') {
      cancelAnimationFrame(this.animId);
    }
    this.animId = null;
  }

  private handleKey(e: KeyboardEvent, pressed: boolean): void {
    // No-op outside walk mode — never block keys when the tool is off.
    if (!this._enabled) return;

    // Never steal keystrokes from form fields / contentEditable surfaces.
    // If walk mode somehow stayed enabled while the user is typing in an
    // input, let the browser handle the key normally.
    const target = e.target as (HTMLElement | null);
    if (target) {
      const tag = target.tagName;
      if (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        (target as HTMLElement).isContentEditable
      ) {
        return;
      }
    }

    switch (e.code) {
      case 'KeyW':
      case 'ArrowUp':
        this.keys.forward = pressed;
        break;
      case 'KeyS':
      case 'ArrowDown':
        this.keys.backward = pressed;
        break;
      case 'KeyA':
      case 'ArrowLeft':
        this.keys.left = pressed;
        break;
      case 'KeyD':
      case 'ArrowRight':
        this.keys.right = pressed;
        break;
      case 'KeyE':
      case 'Space':
      case 'PageUp':
        this.keys.up = pressed;
        break;
      case 'KeyQ':
      case 'PageDown':
      case 'ControlLeft':
      case 'ControlRight':
        this.keys.down = pressed;
        break;
      case 'ShiftLeft':
      case 'ShiftRight':
        // Shift is the sprint modifier (standard FPS convention).
        // Previously it doubled as "down" — that was a footgun because
        // it conflicted with browser default shift behaviour and was
        // undocumented in the on-screen hint.
        this.keys.sprint = pressed;
        break;
      default:
        // Unhandled key — let the browser do its normal thing (Esc,
        // F-keys, browser shortcuts, etc.).
        return;
    }

    // Reached only when the key matched a walk-mode binding above.
    // Suppress default browser behaviour (page scroll on arrows /
    // Space / PageUp / PageDown, Ctrl shortcuts, Shift selection)
    // AND stop propagation so panel/sidebar handlers never see it.
    e.preventDefault();
    e.stopPropagation();
  }
}
