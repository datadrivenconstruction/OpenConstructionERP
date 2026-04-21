/**
 * Keyboard shortcut map for the PDF Takeoff toolbar.
 *
 * Mapping (Q1 UX spec):
 *   V → Select          D → Distance     P → Polyline
 *   A → Area            O → Volume       C → Count
 *   R → Rectangle       T → Text         H → Highlight
 *   W → Cloud           X → Arrow        Esc → cancel
 */

import type { MeasureTool } from './takeoff-types';

/** Single-key → tool map (lowercased keys). */
export const TOOL_SHORTCUT_MAP: Readonly<Record<string, MeasureTool>> = {
  v: 'select',
  d: 'distance',
  p: 'polyline',
  a: 'area',
  o: 'volume',
  c: 'count',
  r: 'rectangle',
  t: 'text',
  h: 'highlight',
  w: 'cloud',
  x: 'arrow',
};

/** Reverse map — tool → uppercase shortcut letter, for tooltip suffixes. */
export const SHORTCUT_LETTER: Readonly<Record<MeasureTool, string>> = {
  select: 'V',
  distance: 'D',
  polyline: 'P',
  area: 'A',
  volume: 'O',
  count: 'C',
  rectangle: 'R',
  text: 'T',
  highlight: 'H',
  cloud: 'W',
  arrow: 'X',
};

/**
 * Resolve a raw keyboard event `key` to the matching tool, or `null` if the
 * key is not a tool shortcut.  Case-insensitive.
 */
export function shortcutToTool(key: string): MeasureTool | null {
  if (!key || key.length !== 1) return null;
  return TOOL_SHORTCUT_MAP[key.toLowerCase()] ?? null;
}

/** Build a tooltip label with the shortcut letter suffix. */
export function labelWithShortcut(label: string, tool: MeasureTool): string {
  const letter = SHORTCUT_LETTER[tool];
  return letter ? `${label} (${letter})` : label;
}

/**
 * Guard: should a keyboard shortcut fire in the current focus context?
 *
 * Returns false when the event target is a text input, textarea or
 * contenteditable element — so typing in the properties panel never
 * switches tools.
 */
export function shouldHandleShortcut(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return true;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return false;
  if (target.isContentEditable) return false;
  return true;
}
