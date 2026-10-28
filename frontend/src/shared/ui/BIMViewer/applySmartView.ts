// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// applySmartView — pure helper that mutates a Three.js scene from a
// SmartView evaluator result.
//
// Counter-intuitive note: a SmartView is RULE-based, not snapshot-based.
// The backend evaluator already collapsed the rule list into a per-element
// ``ElementState`` map; this helper just paints those states onto the
// mesh graph. We touch ``mesh.visible``, ``mesh.material.color`` and
// ``mesh.material.opacity`` — never the geometry.
//
// Material safety:
//   - Originals are cached on ``mesh.userData._smartViewOriginalMaterial``
//     the first time we touch the mesh. ``revertSmartView`` restores them.
//   - We clone the material before mutating so two models in a federation
//     that happen to share a baked material (common with DDC RVT exports)
//     don't bleed each other's smart-view colour.
//   - The cloned material is parked on ``mesh.userData._smartViewMaterial``
//     so re-applying the same view doesn't duplicate clones on every call.
//
// This file is INTENTIONALLY framework-free — no React, no Zustand. It
// takes a duck-typed ``viewer`` argument so it's easy to unit-test with a
// hand-rolled fake scene.

import * as THREE from 'three';

/** Per-element resolved visual state, identical to the backend
 *  ``ElementState`` Pydantic schema. */
export interface SmartViewElementState {
  visible: boolean;
  color: string | null;
  opacity: number;
}

/** Backend evaluator output, keyed by element ``stable_id`` (the GUID
 *  that survives re-imports — *not* the internal UUID). */
export type SmartViewEvalResult = Record<string, SmartViewElementState>;

/** Subset of the Three.js scene API this helper relies on. The real
 *  BIMViewer composes a {@link THREE.Scene} as ``scene`` with an
 *  ``elementGroup`` Object3D as ``root``; tests pass a hand-rolled
 *  Group so we keep the contract narrow. */
export interface SmartViewViewerHandle {
  scene: THREE.Object3D;
  /** The container under which BIM element meshes live. The traversal
   *  starts here, which keeps grid/lights/measure overlays untouched. */
  root: THREE.Object3D;
}

/** Internal: the userData fields applySmartView reads / writes. */
interface SmartViewUserData {
  elementData?: { stable_id?: string; id?: string };
  /** Cached pristine material — captured on first paint, restored by
   *  {@link revertSmartView}. May be an array on multi-material meshes. */
  _smartViewOriginalMaterial?: THREE.Material | THREE.Material[];
  /** Cached clone we keep mutating across re-applies. Cleared on revert. */
  _smartViewMaterial?: THREE.Material;
  /** Set to ``true`` when applySmartView itself flipped this mesh hidden.
   *  {@link revertSmartView} only re-shows meshes carrying this tag, so it
   *  never resurrects elements hidden by context-menu Hide / Layers tab /
   *  filter / isolation (those flips don't carry the tag). */
  _smartViewHidVisible?: boolean;
}

function looksLikeMesh(obj: THREE.Object3D): obj is THREE.Mesh {
  // ``THREE.Mesh`` carries an ``isMesh`` discriminator; using the flag
  // avoids the ``instanceof`` realm-mismatch hazard when fake scenes are
  // used in tests.
  return Boolean((obj as { isMesh?: boolean }).isMesh);
}

function getStableId(mesh: THREE.Mesh): string | undefined {
  const ud = mesh.userData as SmartViewUserData;
  const stable = ud.elementData?.stable_id;
  if (stable) return stable;
  // Fall back to elementData.id — useful in showcase models where
  // stable_id is unset but the canonical id IS the IFC GUID.
  return ud.elementData?.id;
}

function ensureCloneableMaterial(
  mesh: THREE.Mesh,
): THREE.Material | null {
  const ud = mesh.userData as SmartViewUserData;
  // Already have a smart-view clone? Reuse it so opacity/colour edits
  // are O(1) instead of O(clones).
  if (ud._smartViewMaterial) return ud._smartViewMaterial;

  const current = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
  if (!current) return null;

  // Snapshot the pristine material on FIRST touch only; later re-applies
  // would otherwise overwrite the original with our clone.
  if (!ud._smartViewOriginalMaterial) {
    ud._smartViewOriginalMaterial = mesh.material as
      | THREE.Material
      | THREE.Material[];
  }

  // Clone so federation siblings don't bleed colour.  ``clone`` is
  // available on every material subclass shipped by three.js.
  const cloned = (current as THREE.Material & {
    clone: () => THREE.Material;
  }).clone();
  ud._smartViewMaterial = cloned;
  mesh.material = cloned;
  return cloned;
}

function applyColour(material: THREE.Material, hex: string): void {
  // Many materials carry a ``.color`` property (MeshBasicMaterial,
  // MeshStandardMaterial, MeshLambertMaterial, MeshPhongMaterial,
  // MeshPhysicalMaterial, MeshMatcapMaterial, LineBasicMaterial,
  // PointsMaterial). Guard via a duck-type so applying to materials
  // without ``.color`` (e.g. ShaderMaterial) is a silent no-op rather
  // than a crash.
  const m = material as THREE.Material & { color?: THREE.Color };
  if (m.color && typeof m.color.setStyle === 'function') {
    try {
      m.color.setStyle(hex);
    } catch {
      // Invalid hex — fall through, leaving the previous colour.
    }
  }
}

function applyOpacity(material: THREE.Material, opacity: number): void {
  // Three.js requires both ``transparent`` and ``opacity`` to take effect.
  // Re-enabling ``transparent`` for fully-opaque pixels has a small
  // performance cost (alpha-sorted draw call), so flip it off when we
  // can.
  const clamped = Math.max(0, Math.min(1, opacity));
  material.opacity = clamped;
  material.transparent = clamped < 1;
  material.needsUpdate = true;
}

/**
 * Paint a SmartView evaluator result onto every relevant mesh under
 * ``viewer.root``.
 *
 * Idempotent — re-calling with the same result is cheap and harmless;
 * re-calling with a different result just overwrites the visual state.
 *
 * @returns count of meshes whose visual state was changed (handy for
 *   debug logging / test assertions).
 */
export function applySmartView(
  viewer: SmartViewViewerHandle,
  evalResult: SmartViewEvalResult,
): number {
  if (!viewer || !viewer.root) return 0;
  let touched = 0;

  viewer.root.traverse((obj) => {
    if (!looksLikeMesh(obj)) return;
    const mesh = obj;
    const stable = getStableId(mesh);
    if (!stable) return;
    const state = evalResult[stable];
    if (!state) return;

    const ud = mesh.userData as SmartViewUserData;
    // Tag meshes WE hide so revertSmartView can re-show exactly those and
    // leave alone anything hidden by Hide / Layers / filter / isolation.
    if (!state.visible) {
      ud._smartViewHidVisible = true;
    } else {
      delete ud._smartViewHidVisible;
    }
    mesh.visible = state.visible;

    if (state.color || state.opacity < 1) {
      const material = ensureCloneableMaterial(mesh);
      if (material) {
        if (state.color) applyColour(material, state.color);
        applyOpacity(material, state.opacity);
        touched += 1;
      }
    } else {
      // visible-but-default-colour: if we previously cloned a material
      // for this mesh, restore the original look so the swatch doesn't
      // freeze on the last colour.
      if (ud._smartViewOriginalMaterial) {
        mesh.material = ud._smartViewOriginalMaterial;
        delete ud._smartViewMaterial;
      }
      touched += 1;
    }
  });

  return touched;
}

/**
 * Restore every mesh under ``viewer.root`` to its pre-SmartView state.
 *
 * Safe to call when no SmartView was applied — meshes without a cached
 * original are left alone.
 *
 * @returns count of meshes whose material/visibility was reset.
 */
export function revertSmartView(viewer: SmartViewViewerHandle): number {
  if (!viewer || !viewer.root) return 0;
  let touched = 0;

  viewer.root.traverse((obj) => {
    if (!looksLikeMesh(obj)) return;
    const mesh = obj;
    const ud = mesh.userData as SmartViewUserData;
    if (ud._smartViewOriginalMaterial) {
      mesh.material = ud._smartViewOriginalMaterial;
      delete ud._smartViewOriginalMaterial;
      delete ud._smartViewMaterial;
      touched += 1;
    }
    // Only restore visibility for meshes WE hid (tagged on apply). A bare
    // `mesh.visible = true` here would resurrect elements hidden by the
    // context-menu Hide, the Layers tab, a category filter, or an active
    // isolate — none of which the SmartView owns. Clear the tag so a later
    // hide-then-revert cycle stays correct.
    if (ud._smartViewHidVisible) {
      mesh.visible = true;
      delete ud._smartViewHidVisible;
      touched += 1;
    }
  });

  return touched;
}
