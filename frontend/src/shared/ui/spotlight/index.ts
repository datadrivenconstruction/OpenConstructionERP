// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Spotlight primitives — the shared engine behind the anchored coach-marks
// (ProductTour + ModuleGuide). Consume these instead of re-deriving the
// measurement / placement / scrim logic in each component.

export {
  placeTooltip,
  centerOfViewport,
  measureSpotlight,
  TOOLTIP_W,
  TOOLTIP_H,
  TOOLTIP_OFFSET,
  SPOTLIGHT_PADDING,
  VIEWPORT_MARGIN,
} from './placeTooltip';
export type { SpotlightRect, TooltipCoords, TooltipPosition } from './placeTooltip';

export {
  useSpotlightTarget,
  SPOTLIGHT_REVEAL_EVENT,
} from './useSpotlightTarget';
export type {
  SpotlightStatus,
  SpotlightTarget,
  UseSpotlightTargetOptions,
} from './useSpotlightTarget';

export { SpotlightScrim } from './SpotlightScrim';
export type { SpotlightScrimProps, SpotlightAccent } from './SpotlightScrim';
