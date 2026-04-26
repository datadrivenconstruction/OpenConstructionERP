/**
 * Barrel export for the EAC visual block editor canvas (EAC §3.2).
 *
 * Consumers (page shells, route configuration, tests) import from this file
 * rather than reaching into individual components, so the internal layout
 * can evolve without breaking call sites.
 */
export { BlockCanvas, CANVAS_DROPPABLE_ID } from './BlockCanvas';
export type { BlockCanvasProps } from './BlockCanvas';

export { BlockNode } from './BlockNode';
export type { BlockNodeData, BlockNodeProps } from './BlockNode';

export { SlotConnection } from './SlotConnection';
export type { SlotConnectionData, SlotConnectionEdge, SlotConnectionProps } from './SlotConnection';

export { CanvasToolbar } from './CanvasToolbar';
export type { CanvasToolbarProps } from './CanvasToolbar';

export {
  useBlockCanvasStore,
  selectCanRedo,
  selectCanUndo,
  selectSelectedBlocks,
} from './useBlockCanvasStore';
export type {
  BlockCanvasActions,
  BlockCanvasState,
  BlockCanvasStore,
  CanvasBlock,
  CanvasConnection,
} from './useBlockCanvasStore';

export {
  BLOCK_KIND_TO_COLOR,
  SLOT_TYPE_COMPATIBILITY,
  buildDropPayload,
  canConnectSlots,
  colorForKind,
  isSlotCompatible,
} from './dnd';
export type {
  CanvasDropPayload,
  SlotDataType,
  SlotDefinition,
  SlotDirection,
} from './dnd';
