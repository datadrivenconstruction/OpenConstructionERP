/**
 * WalkMode — first-person walk-through navigation.
 *
 * Two look modes:
 *   - DRAG-TO-LOOK (default) — the OS cursor stays visible and the browser
 *     never shows the "site has taken control of your cursor" banner. The
 *     user holds the primary mouse button and drags to look around. This is
 *     the default because pointer-lock hides the cursor and pops a native
 *     warning, which users read as the page misbehaving (pdf07).
 *   - POINTER-LOCK / FPS (opt-in via `lockCursor: true`) — true first-person
 *     mouse-look built on three.js `PointerLockControls`. The cursor is
 *     hidden and movementX/Y drives the camera continuously. Unchanged from
 *     the original behaviour.
 *
 * Controls (both modes; mirrors BIM coordination tool walk mode):
 *   - mouse drag (default) / locked mouse (FPS) → look
 *   - W/A/S/D / arrow keys      → walk
 *   - Q / PageDown / Ctrl       → down
 *   - E / Space / PageUp        → up
 *   - Shift                     → sprint (3× speed)
 *   - ESC                       → release pointer-lock (browser drives it in
 *                                 FPS mode); callers also listen for Escape
 *                                 on window to fully disable the tool.
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
  /** Opt into true pointer-lock (FPS) mouse-look. Default `false` →
   *  drag-to-look (cursor stays visible, no native pointer-lock banner).
   *  Set `true` only when the host explicitly wants the captured-cursor
   *  FPS experience. */
  lockCursor?: boolean;
  /** Optional callback fired whenever the camera moved during a tick.
   *  The host wires this to `SceneManager.requestRender()` so the
   *  on-demand render loop redraws — without it the camera moves but the
   *  user sees no motion because OrbitControls (the only other source of
   *  render invalidation) is disabled in walk mode. */
  onChange?: () => void;
  /** Optional callback fired when pointer-lock is lost UNEXPECTEDLY while
   *  walk mode is still active (e.g. the user alt-tabbed away and the
   *  browser released the cursor without the user toggling the tool off).
   *  The host wires this to its own teardown (disable walk + re-enable
   *  OrbitControls + clear the toolbar pressed state) so the user is never
   *  stranded controller-less. NOT fired during an intentional `disable()`
   *  or `dispose()`. Only relevant in pointer-lock (FPS) mode. */
  onExitRequest?: () => void;
}

const DEFAULT_SPEED = 2; // m/s
const SPRINT_MULTIPLIER = 3;
/** Drag-to-look sensitivity: radians of camera rotation per pixel of mouse
 *  movement. ~0.002 rad/px ≈ a full 180° sweep over ~1500 px, comfortable
 *  for a trackpad or mouse drag. */
const DRAG_LOOK_SENSITIVITY = 0.002;
/** Pitch clamp (radians) so drag-look can't roll the camera past straight
 *  up / down (which would invert the view and feel broken). */
const MAX_PITCH = 1.55;

export class WalkMode {
  /** Reusable scratch vectors for drag-to-look movement so each tick()
   *  doesn't allocate. Shared across instances — only ever touched inside a
   *  single synchronous tick() call, never retained. */
  private static _fwd = new THREE.Vector3();
  private static _right = new THREE.Vector3();

  private camera: THREE.Camera;
  // Renderer kept on the API for symmetry with SectionBox / MeasureTool;
  // WalkMode itself drives the PointerLockControls which holds its own
  // domElement reference. Underscored to silence noUnusedLocals.
  private _renderer: THREE.WebGLRenderer;
  private domElement: HTMLElement;
  private orbitControls?: { enabled: boolean };
  private onChange?: () => void;
  private onExitRequest?: () => void;
  /** When true, `enable()` builds PointerLockControls and captures the
   *  cursor (FPS). When false (default), drag-to-look is used instead. */
  private lockCursor: boolean;

  private controls: PointerLockControls | null = null;
  private _enabled = false;
  private _locked = false;
  /** Drag-to-look state (only used when `lockCursor` is false). */
  private _isDragging = false;
  /** Accumulated yaw/pitch for drag-to-look, kept in a YXZ Euler so we can
   *  clamp pitch independently of yaw without gimbal surprises. */
  private _lookEuler = new THREE.Euler(0, 0, 0, 'YXZ');
  /** True only while `disable()` is tearing the tool down. Used so the
   *  pointer-lock-loss handler can tell an intentional teardown apart from
   *  the browser dropping the lock (alt-tab / Esc) while we stay enabled. */
  private _disabling = false;
  /** True once the user has actually acquired the lock at least once. We
   *  only auto-exit on a LOSS that follows a successful lock — never on the
   *  initial gap between `enable()` and the first lock acquisition (which
   *  may be deferred to a click when there's no user gesture). */
  private _everLocked = false;
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
    this._everLocked = true;
    for (const l of this.lockListeners) l(true);
  };
  private onUnlock = (): void => {
    const wasLocked = this._locked;
    this._locked = false;
    for (const l of this.lockListeners) l(false);
    // Unexpected loss: the lock dropped (alt-tab / browser Esc) while walk
    // mode is still enabled and we are NOT in the middle of an intentional
    // teardown. Rather than strand the user with no cursor and no orbit,
    // ask the host to gracefully exit walk mode. Guarded on `wasLocked` /
    // `_everLocked` so the initial pre-lock gap never triggers an exit.
    if (this._enabled && !this._disabling && wasLocked && this._everLocked) {
      this.onExitRequest?.();
    }
  };
  /** Acquire pointer lock on a user click, but ONLY before the first
   *  successful lock — i.e. when `enable()`'s immediate `lock()` was
   *  rejected for lacking a user gesture. After the user has been locked
   *  once, an unexpected loss auto-exits walk mode (see `onUnlock`), so we
   *  must NOT silently grab the lock back here — that would fight the exit
   *  and re-hide the cursor the user just got back. */
  private onClickReacquire = (): void => {
    if (!this._enabled || this._locked || this._everLocked || !this.controls) {
      return;
    }
    try {
      this.controls.lock();
    } catch {
      /* still no user gesture; ignore */
    }
  };

  /* ── Drag-to-look handlers (used only when `lockCursor` is false) ──── */

  private onDragPointerDown = (e: PointerEvent): void => {
    // Only the primary (left) button starts a look-drag. Other buttons are
    // left alone so middle/right are free for any future host behaviour.
    if (!this._enabled || e.button !== 0) return;
    this._isDragging = true;
    // Seed the look Euler from the camera's CURRENT orientation so the
    // first drag doesn't snap the view.
    this._lookEuler.setFromQuaternion(this.camera.quaternion);
    this.domElement.style.cursor = 'grabbing';
    try {
      this.domElement.setPointerCapture?.(e.pointerId);
    } catch {
      /* setPointerCapture can throw if the pointer is already gone */
    }
    // Mirror PointerLockControls' lock semantics so the hint overlay /
    // on-demand renderer react to drag start exactly as they did to lock.
    if (!this._locked) {
      this._locked = true;
      this._everLocked = true;
      for (const l of this.lockListeners) l(true);
    }
    e.preventDefault();
  };

  private onDragPointerMove = (e: PointerEvent): void => {
    if (!this._enabled || !this._isDragging) return;
    // Yaw left/right on X movement, pitch up/down on Y movement. Negative
    // because dragging right should rotate the view right (camera yaw is
    // CCW about +Y, so a rightward drag is a negative yaw delta).
    this._lookEuler.y -= e.movementX * DRAG_LOOK_SENSITIVITY;
    this._lookEuler.x -= e.movementY * DRAG_LOOK_SENSITIVITY;
    // Clamp pitch so we never flip past vertical.
    this._lookEuler.x = Math.max(-MAX_PITCH, Math.min(MAX_PITCH, this._lookEuler.x));
    this.camera.quaternion.setFromEuler(this._lookEuler);
    this.onChange?.();
    e.preventDefault();
  };

  private onDragPointerUp = (e: PointerEvent): void => {
    if (!this._isDragging) return;
    this._isDragging = false;
    this.domElement.style.cursor = 'grab';
    try {
      this.domElement.releasePointerCapture?.(e.pointerId);
    } catch {
      /* already released */
    }
    // Drag ended — flip the "locked" mirror back off so the FPS-only hint
    // overlay / crosshair hide (drag look has no crosshair).
    if (this._locked) {
      this._locked = false;
      for (const l of this.lockListeners) l(false);
    }
  };

  constructor(args: WalkModeArgs) {
    this.camera = args.camera;
    this._renderer = args.renderer;
    this.domElement = args.domElement;
    this.orbitControls = args.orbitControls;
    this.lockCursor = args.lockCursor ?? false;
    this.onChange = args.onChange;
    this.onExitRequest = args.onExitRequest;
    void this._renderer;
  }

  isEnabled(): boolean {
    return this._enabled;
  }

  isLocked(): boolean {
    return this._locked;
  }

  /** True when this instance uses true pointer-lock (FPS) mouse-look, false
   *  for the default drag-to-look mode. Lets the host show FPS-only chrome
   *  (e.g. the centred crosshair reticle) without re-deriving the mode. */
  isPointerLockMode(): boolean {
    return this.lockCursor;
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
        'WalkMode.enable(): OrbitControls is still active - disable it first to avoid camera-fight rendering bugs.',
      );
    }
    this._enabled = true;
    this._everLocked = false;
    this._disabling = false;
    this._isDragging = false;

    // `capture: true` ensures we intercept arrow/space/etc BEFORE they
    // bubble to any panel/sidebar that listens for them (which used to
    // make panels appear to move alongside the camera).
    window.addEventListener('keydown', this.onKeyDown, { capture: true });
    window.addEventListener('keyup', this.onKeyUp, { capture: true });

    if (this.lockCursor) {
      // ── FPS / pointer-lock path (opt-in) ──
      this.controls = new PointerLockControls(this.camera, this.domElement);
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
    } else {
      // ── Drag-to-look path (default) ──
      // No PointerLockControls, no requestPointerLock — the OS cursor stays
      // visible and the browser never shows its "controlling your cursor"
      // banner. The user holds the primary button and drags to look.
      this.controls = null;
      this._lookEuler.setFromQuaternion(this.camera.quaternion);
      this.domElement.style.cursor = 'grab';
      this.domElement.addEventListener('pointerdown', this.onDragPointerDown);
      this.domElement.addEventListener('pointermove', this.onDragPointerMove);
      this.domElement.addEventListener('pointerup', this.onDragPointerUp);
      this.domElement.addEventListener('pointercancel', this.onDragPointerUp);
    }

    this.lastTickMs = typeof performance !== 'undefined' ? performance.now() : Date.now();
    this.startLoop();
  }

  disable(): void {
    if (!this._enabled) return;
    this._enabled = false;
    // Mark teardown so the `unlock` event our own `controls.unlock()` below
    // dispatches is treated as intentional (no auto-exit re-entrancy).
    this._disabling = true;
    this.stopLoop();

    window.removeEventListener('keydown', this.onKeyDown, { capture: true });
    window.removeEventListener('keyup', this.onKeyUp, { capture: true });

    if (this.controls) {
      // ── FPS / pointer-lock teardown ──
      this.domElement.removeEventListener('click', this.onClickReacquire);
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
    } else {
      // ── Drag-to-look teardown ──
      this.domElement.removeEventListener('pointerdown', this.onDragPointerDown);
      this.domElement.removeEventListener('pointermove', this.onDragPointerMove);
      this.domElement.removeEventListener('pointerup', this.onDragPointerUp);
      this.domElement.removeEventListener('pointercancel', this.onDragPointerUp);
      this.domElement.style.cursor = '';
      this._isDragging = false;
    }
    if (this._locked) {
      this._locked = false;
      for (const l of this.lockListeners) l(false);
    }
    // Reset key state so a leftover key-up arriving after disable()
    // does not poison the next enable().
    for (const k of Object.keys(this.keys)) this.keys[k] = false;
    this._disabling = false;
    this._everLocked = false;
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
    if (!this._enabled) return;
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

    if (moved) {
      if (this.controls) {
        // FPS path: PointerLockControls knows how to translate the camera
        // along its own ground-projected forward/right axes.
        if (this.keys.forward) this.controls.moveForward(distance);
        if (this.keys.backward) this.controls.moveForward(-distance);
        if (this.keys.right) this.controls.moveRight(distance);
        if (this.keys.left) this.controls.moveRight(-distance);
      } else {
        // Drag-to-look path: derive camera-relative forward/right from the
        // camera quaternion ourselves (no controls object to lean on).
        // Forward is ground-projected (Y zeroed) so WASD walks the floor
        // plane rather than flying into the model when the user looks up.
        const forward = WalkMode._fwd
          .set(0, 0, -1)
          .applyQuaternion(this.camera.quaternion);
        forward.y = 0;
        if (forward.lengthSq() > 1e-8) forward.normalize();
        const right = WalkMode._right
          .set(1, 0, 0)
          .applyQuaternion(this.camera.quaternion);
        right.y = 0;
        if (right.lengthSq() > 1e-8) right.normalize();

        if (this.keys.forward) this.camera.position.addScaledVector(forward, distance);
        if (this.keys.backward) this.camera.position.addScaledVector(forward, -distance);
        if (this.keys.right) this.camera.position.addScaledVector(right, distance);
        if (this.keys.left) this.camera.position.addScaledVector(right, -distance);
      }
      // Up/down are world-Y in both modes.
      if (this.keys.up) this.camera.position.y += distance;
      if (this.keys.down) this.camera.position.y -= distance;
    }

    // While pointer-lock is active the user is also free-looking via mouse
    // (PointerLockControls mutates the camera quaternion directly without
    // notifying us), so we have to redraw every frame the cursor is
    // captured — not just frames where a key moved the position. Drag-look
    // already pings onChange() on each pointermove, so here we only need to
    // cover key-driven motion + the FPS free-look case.
    if (moved || (this.controls && this._locked)) {
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
