// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * useBcfCapture - the "Raise issue here" capture flow.
 *
 * This hook deliberately does NOT know about any 3D viewer. It talks to a
 * small injected {@link BcfViewerBridge} that yields the three things a BCF
 * viewpoint needs: the current camera, the selected element GUIDs, and the
 * WebGL canvas to snapshot. The integrator wires that bridge to whichever
 * viewer is on screen, so this module stays viewer-agnostic and testable.
 *
 * Raising an issue is two calls: create the topic, then attach a viewpoint
 * carrying the camera, the selection, and a PNG snapshot. The topic is the
 * source of truth, so a viewpoint failure never loses the issue - it is
 * reported via `viewpointFailed` instead of throwing.
 */

import { useCallback, useMemo } from 'react';

import { toNum } from '@/shared/lib/money';

import {
  addViewpoint,
  createTopic,
  type OrthogonalCamera,
  type PerspectiveCamera,
  type Topic,
  type TopicCreate,
  type Vec3,
  type Viewpoint,
} from './api';

/* ── Injected viewer bridge ────────────────────────────────────────────── */

/** A plain 3-component vector as most 3D libraries expose it. */
export interface ViewerVec3 {
  x: number;
  y: number;
  z: number;
}

/**
 * A neutral snapshot of the viewer camera, mapped to BCF by this module.
 *
 * `direction` is the normalised look direction (target minus eye), `up` is the
 * camera up vector. Set `orthogonal: true` to emit a BCF OrthogonalCamera
 * (with `viewToWorldScale`) instead of a PerspectiveCamera (with
 * `fieldOfView`, in degrees).
 */
export interface ViewerCameraSnapshot {
  position: ViewerVec3;
  direction: ViewerVec3;
  up: ViewerVec3;
  fieldOfView?: number;
  orthogonal?: boolean;
  viewToWorldScale?: number;
}

/**
 * The seam between this flow and a concrete viewer. Every method is called
 * defensively (wrapped in try/catch) so a throwing or half-initialised viewer
 * degrades to "no viewpoint" rather than crashing the capture.
 */
export interface BcfViewerBridge {
  /** Current camera state, or null when the viewer is not ready. */
  getCamera: () => ViewerCameraSnapshot | null;
  /** Selected element IFC GUIDs / stable ids (empty when nothing is picked). */
  getSelectedGuids: () => string[];
  /** The WebGL canvas to snapshot, or null when unavailable. */
  getCanvas: () => HTMLCanvasElement | null;
  /**
   * Optional snapshot override: return bare base64 PNG (no data-url prefix).
   *
   * Use this when the WebGL renderer was created without
   * `preserveDrawingBuffer` - `getCanvas().toDataURL()` then reads a cleared
   * buffer and yields a blank frame. An integrator that controls the renderer
   * can force a render and read the pixels here. When omitted, capture falls
   * back to `getCanvas()` + `toDataURL`.
   */
  getSnapshotBase64?: () => string | null;
}

/* ── Pure helpers (exported for reuse + testing) ───────────────────────── */

function vec(v: ViewerVec3 | null | undefined): Vec3 {
  return { x: toNum(v?.x), y: toNum(v?.y), z: toNum(v?.z) };
}

/** Call a bridge getter without ever letting it throw into the caller. */
function safeCall<T>(fn: (() => T) | null | undefined): T | null {
  try {
    return typeof fn === 'function' ? fn() : null;
  } catch {
    return null;
  }
}

/**
 * Capture a PNG from a canvas as bare base64 (no `data:image/png;base64,`
 * prefix - that is what the backend's `snapshot_png_b64` expects).
 *
 * Returns null for a missing canvas, a tainted canvas (`toDataURL` throws), or
 * an empty result. WebGL canvases only yield pixels when the context was
 * created with `preserveDrawingBuffer: true` or `toDataURL` is called in the
 * same frame as the draw - both are the integrator's concern; capture here is
 * always best-effort.
 */
export function captureCanvasBase64(canvas: HTMLCanvasElement | null): string | null {
  if (!canvas) return null;
  try {
    const dataUrl = canvas.toDataURL('image/png');
    const comma = dataUrl.indexOf(',');
    if (comma < 0) return null;
    const b64 = dataUrl.slice(comma + 1);
    return b64.length > 0 ? b64 : null;
  } catch {
    return null;
  }
}

/** Map a neutral camera snapshot to the matching BCF camera field. */
export function cameraToBcf(cam: ViewerCameraSnapshot | null): {
  perspective_camera?: PerspectiveCamera;
  orthogonal_camera?: OrthogonalCamera;
} {
  if (!cam) return {};
  if (cam.orthogonal) {
    const orthogonal_camera: OrthogonalCamera = {
      camera_view_point: vec(cam.position),
      camera_direction: vec(cam.direction),
      camera_up_vector: vec(cam.up),
      // A zero scale would be meaningless; fall back to 1 (BCF default).
      view_to_world_scale: toNum(cam.viewToWorldScale) || 1,
    };
    return { orthogonal_camera };
  }
  const perspective_camera: PerspectiveCamera = {
    camera_view_point: vec(cam.position),
    camera_direction: vec(cam.direction),
    camera_up_vector: vec(cam.up),
    field_of_view: toNum(cam.fieldOfView) || 60,
  };
  return { perspective_camera };
}

/* ── Captured context ──────────────────────────────────────────────────── */

/** Everything captured from the viewer at one instant. */
export interface CapturedContext {
  camera: ViewerCameraSnapshot | null;
  guids: string[];
  snapshotB64: string | null;
}

/** Snapshot the viewer once. Best-effort: any missing piece is just null / []. */
export function captureViewerContext(bridge: BcfViewerBridge): CapturedContext {
  const camera = safeCall(bridge.getCamera);
  const guids = safeCall(bridge.getSelectedGuids) ?? [];
  // Prefer an integrator-supplied snapshot (correct WebGL capture timing);
  // otherwise read the canvas directly.
  const provided = safeCall(bridge.getSnapshotBase64);
  const snapshotB64 = provided ?? captureCanvasBase64(safeCall(bridge.getCanvas));
  return { camera, guids, snapshotB64 };
}

/** True when a captured context carries anything worth a viewpoint. */
export function hasCapturedContent(ctx: CapturedContext): boolean {
  return Boolean(ctx.camera) || ctx.guids.length > 0 || Boolean(ctx.snapshotB64);
}

/* ── Raise-issue hook ──────────────────────────────────────────────────── */

/** Fields collected by the "Raise issue" form. */
export interface RaiseIssueInput {
  title: string;
  description?: string;
  priority?: string;
  assignedTo?: string;
  /** ISO date (YYYY-MM-DD) or datetime; empty clears it. */
  dueDate?: string;
  labels?: string[];
  bimModelId?: string | null;
  topicStatus?: string;
}

/** Outcome of raising an issue. */
export interface RaiseIssueResult {
  topic: Topic;
  viewpoint: Viewpoint | null;
  /** True when the topic was created but its viewpoint POST failed. */
  viewpointFailed: boolean;
}

function trimmedOrNull(v: string | null | undefined): string | null {
  const s = (v ?? '').trim();
  return s.length > 0 ? s : null;
}

/**
 * Returns `raiseIssue(input, capture?)` plus a `capture()` shortcut.
 *
 * `capture()` snapshots the viewer now (used to build a live preview before
 * the user commits). Pass that same context back into `raiseIssue` so the
 * issue records exactly what the user previewed; omit it and `raiseIssue`
 * captures at submit time instead.
 */
export function useBcfCapture(projectId: string, bridge: BcfViewerBridge) {
  const capture = useCallback(
    (): CapturedContext => captureViewerContext(bridge),
    [bridge],
  );

  const raiseIssue = useCallback(
    async (input: RaiseIssueInput, captured?: CapturedContext): Promise<RaiseIssueResult> => {
      const ctx = captured ?? captureViewerContext(bridge);

      // 1. Create the topic. A failure here throws to the caller (the form
      //    stays open and shows the error).
      const topicBody: TopicCreate = {
        title: input.title.trim(),
        description: trimmedOrNull(input.description),
        topic_status: trimmedOrNull(input.topicStatus) ?? 'Open',
        priority: trimmedOrNull(input.priority),
        assigned_to: trimmedOrNull(input.assignedTo),
        due_date: trimmedOrNull(input.dueDate),
        labels: input.labels ?? [],
        bim_model_id: trimmedOrNull(input.bimModelId),
      };
      const topic = await createTopic(projectId, topicBody);

      // 2. Attach the viewpoint only when there is something to record. A
      //    viewpoint failure must not lose the already-created topic, so it is
      //    reported via `viewpointFailed` rather than thrown.
      let viewpoint: Viewpoint | null = null;
      let viewpointFailed = false;
      if (hasCapturedContent(ctx)) {
        try {
          viewpoint = await addViewpoint(projectId, topic.guid, {
            ...cameraToBcf(ctx.camera),
            components: {
              selection: ctx.guids,
              visible: [],
              hidden: [],
              default_visibility: true,
            },
            element_stable_ids: ctx.guids,
            snapshot_png_b64: ctx.snapshotB64,
          });
        } catch {
          viewpointFailed = true;
        }
      }

      return { topic, viewpoint, viewpointFailed };
    },
    [projectId, bridge],
  );

  return useMemo(() => ({ raiseIssue, capture }), [raiseIssue, capture]);
}
