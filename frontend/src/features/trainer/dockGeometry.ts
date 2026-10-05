// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Geometry of the Academy task dock, as pure functions (frontend design §4,
// TaskDock). It mirrors the AI dock in features/erp-chat/useFloatingChat.ts.
//
// Three presentations:
//   push   wide screen with room: the panel sits beside the page and the page
//          is padded by its width, so it never covers the form being worked on
//   rail   the learner collapsed the panel, or the screen has no room for it:
//          a 56px strip that still pushes the page, never covers it
//   sheet  phone width: a bottom sheet with a 64px peek, 85vh when expanded
//
// The push/rail decision depends on the SCREEN only (viewport, docked sidebar,
// AI dock), never on the width the learner dragged to: when room is short the
// panel gives up width instead of flipping, so no drag can flip the mode under
// the pointer. Between 640px and the push threshold the panel stays a rail and
// expanding it pushes at the narrowest width (the page reflows, it is never
// covered); TaskDock folds it back to the rail when room runs out (the AI dock
// opens, the window narrows).
//
// Layout contract with index.css (Wave 2, owner of index.css):
//   html[data-trainer-dock="push"]   push AND rail; the shell pads its
//                                    inline end by --oe-trainer-dock-offset
//   html[data-trainer-dock="sheet"]  phone; fixed widgets lift by
//                                    --oe-trainer-sheet-peek
//   --oe-trainer-dock-offset         the panel width, 56px as a rail, 0 as a sheet
//   --oe-trainer-sheet-peek          64px while a sheet is shown
// All of it is removed when the dock is hidden or unmounts.

import { DOCK_WIDTH_MAX, DOCK_WIDTH_MIN, clampDockWidth } from './useTrainerUiStore';

/** Below this viewport width the dock is a bottom sheet. */
export const TRAINER_SHEET_BELOW = 640;
/** Push needs the `lg` breakpoint, where the sidebar docks too. */
export const TRAINER_PUSH_MIN_VIEWPORT = 1024;
/** The page never gets narrower than this next to a pushing panel. */
export const TRAINER_MIN_PAGE_WIDTH = 560;
/** Width of the collapsed rail. */
export const TRAINER_RAIL_WIDTH = 56;
/** Height of the collapsed sheet. */
export const TRAINER_SHEET_PEEK = 64;
/** One arrow-key press on the resize handle. */
export const TRAINER_DOCK_KEY_STEP = 16;

export const TRAINER_DOCK_ATTR = 'data-trainer-dock';
export const TRAINER_DOCK_OFFSET_VAR = '--oe-trainer-dock-offset';
export const TRAINER_SHEET_PEEK_VAR = '--oe-trainer-sheet-peek';

export type TrainerDockMode = 'push' | 'rail' | 'sheet';

export interface DockEnvironment {
  viewportWidth: number;
  /** The docked sidebar width; 0 below the `lg` breakpoint, where it is a drawer. */
  sidebarWidth: number;
  /** Where the AI dock sits (`--oe-ai-dock-widget-offset`), 0 when it is closed. */
  aiOffset: number;
}

/** True when the panel fits beside the page at its narrowest width. */
export function trainerDockFits({ viewportWidth, sidebarWidth, aiOffset }: DockEnvironment): boolean {
  if (viewportWidth < TRAINER_PUSH_MIN_VIEWPORT) return false;
  return viewportWidth - sidebarWidth - aiOffset - DOCK_WIDTH_MIN >= TRAINER_MIN_PAGE_WIDTH;
}

/**
 * The presentation for this screen. `open` is the learner's choice in the
 * store (`dockOpen`); TaskDock folds it to false when the panel stops fitting.
 */
export function resolveTrainerDockMode(env: DockEnvironment & { open: boolean }): TrainerDockMode {
  if (env.viewportWidth < TRAINER_SHEET_BELOW) return 'sheet';
  return env.open ? 'push' : 'rail';
}

/**
 * The widest the panel may be right now: DOCK_WIDTH_MAX, and no wider than
 * what leaves the page TRAINER_MIN_PAGE_WIDTH. Never below DOCK_WIDTH_MIN.
 */
export function trainerDockMaxWidth({ viewportWidth, sidebarWidth, aiOffset }: DockEnvironment): number {
  const room = Math.floor(viewportWidth - sidebarWidth - aiOffset - TRAINER_MIN_PAGE_WIDTH);
  return Math.max(DOCK_WIDTH_MIN, Math.min(DOCK_WIDTH_MAX, room));
}

/** The width actually shown: the preference, capped by the screen. */
export function trainerDockWidth(preferred: number, maxWidth: number): number {
  return Math.min(clampDockWidth(preferred), Math.max(DOCK_WIDTH_MIN, maxWidth));
}

/** What the page pads its inline end by. */
export function trainerDockOffset(mode: TrainerDockMode, width: number): number {
  if (mode === 'push') return Math.round(width);
  if (mode === 'rail') return TRAINER_RAIL_WIDTH;
  return 0;
}

/**
 * Width while dragging the handle on the panel's inline-start edge. Moving
 * away from the panel widens it: left in LTR (panel on the right), right in RTL.
 */
export function trainerWidthFromDrag({
  startWidth,
  startX,
  currentX,
  rtl,
  maxWidth,
}: {
  startWidth: number;
  startX: number;
  currentX: number;
  rtl: boolean;
  maxWidth: number;
}): number {
  const delta = (startX - currentX) * (rtl ? -1 : 1);
  return trainerDockWidth(startWidth + delta, maxWidth);
}

/**
 * Width after a key on the focused resize handle, or null for any other key.
 * The arrow pointing at the page widens the panel, so the arrows swap in RTL.
 * Home and End jump to the narrowest and the widest.
 */
export function trainerWidthFromKey(
  key: string,
  { width, maxWidth, rtl }: { width: number; maxWidth: number; rtl: boolean },
): number | null {
  const towardsPage = rtl ? 'ArrowRight' : 'ArrowLeft';
  const awayFromPage = rtl ? 'ArrowLeft' : 'ArrowRight';
  if (key === towardsPage) return trainerDockWidth(width + TRAINER_DOCK_KEY_STEP, maxWidth);
  if (key === awayFromPage) return trainerDockWidth(width - TRAINER_DOCK_KEY_STEP, maxWidth);
  if (key === 'Home') return DOCK_WIDTH_MIN;
  if (key === 'End') return trainerDockWidth(maxWidth, maxWidth);
  return null;
}

/** Tell the page about the dock (see the layout contract above). */
export function applyTrainerDockLayout(root: HTMLElement, mode: TrainerDockMode, width: number): void {
  root.setAttribute(TRAINER_DOCK_ATTR, mode === 'sheet' ? 'sheet' : 'push');
  root.style.setProperty(TRAINER_DOCK_OFFSET_VAR, `${trainerDockOffset(mode, width)}px`);
  if (mode === 'sheet') root.style.setProperty(TRAINER_SHEET_PEEK_VAR, `${TRAINER_SHEET_PEEK}px`);
  else root.style.removeProperty(TRAINER_SHEET_PEEK_VAR);
}

/** Undo everything applyTrainerDockLayout wrote. */
export function clearTrainerDockLayout(root: HTMLElement): void {
  root.removeAttribute(TRAINER_DOCK_ATTR);
  root.style.removeProperty(TRAINER_DOCK_OFFSET_VAR);
  root.style.removeProperty(TRAINER_SHEET_PEEK_VAR);
}

/** A `NNpx` inline custom property on `root`, or 0. Reads the inline style, so no style recalculation. */
export function readInlinePx(root: HTMLElement, name: string): number {
  const raw = root.style.getPropertyValue(name).trim();
  const px = Number.parseFloat(raw);
  return Number.isFinite(px) && raw.endsWith('px') ? px : 0;
}
