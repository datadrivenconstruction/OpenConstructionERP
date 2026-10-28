// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// internal cache lineage: ddc-lineage:a17f93c4-bim-02
export { BIMViewer, DisciplineToggle } from './BIMViewer';
export type { BIMViewerProps, BIMViewMode } from './BIMViewer';

export { SceneManager } from './SceneManager';
export type { Viewpoint as SceneViewpoint, ViewPreset } from './SceneManager';

export { CameraTween, easeInOutCubic } from './CameraTween';
export type { CameraState } from './CameraTween';

export { default as BIMViewCube } from './BIMViewCube';
export type { BIMViewCubeProps } from './BIMViewCube';

export {
  ElementManager,
  CATEGORICAL_12,
  FIRE_RATING_PALETTE,
  colorForPropertyValue,
  resolveElementProperty,
} from './ElementManager';
export type {
  BIMElementData,
  BIMModelData,
  BIMBoundingBox,
  ColorByPropertyConfig,
  ColorByPropertyPalette,
  PropertyValueCount,
} from './ElementManager';

export { SelectionManager } from './SelectionManager';
export type { SelectionCallbacks } from './SelectionManager';

export { MeasureManager } from './MeasureManager';
export type { Measurement, MeasureState, MeasureKind } from './MeasureManager';

export { ClipManager } from './ClipManager';
export type {
  ClipMode,
  ClipAxis,
  ClipBoxExtent,
  ClipPlaneState,
} from './ClipManager';

export {
  deriveGeometry,
  deriveRelations,
} from './canonicalElementDetails';
export type {
  CanonicalGeometry,
  CanonicalRelation,
  CanonicalBBox,
} from './canonicalElementDetails';

export {
  distance3,
  polygonArea3,
  polygonPerimeter3,
  angleBetween3,
  centroid3,
} from './measureMath';
export type { Vec3 } from './measureMath';

export {
  addViewpoint,
  listViewpoints,
  removeViewpoint,
  renameViewpoint,
  getViewpoint,
  setViewpointScreenshot,
  restoreView,
  DEFAULT_RESTORE_DURATION_MS,
} from './SavedViewsStore';
export type {
  Viewpoint,
  SavedBIMFilterState,
  BIMClipState,
} from './SavedViewsStore';
