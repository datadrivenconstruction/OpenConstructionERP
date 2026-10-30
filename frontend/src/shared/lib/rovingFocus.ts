// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Roving focus for a grid of choice tiles: the group is one Tab stop and the
// arrow keys move between tiles, so a long list does not bury the buttons after it.

import type { KeyboardEvent } from 'react';

const NEXT = new Set(['ArrowRight', 'ArrowDown']);
const PREV = new Set(['ArrowLeft', 'ArrowUp']);

/**
 * Key handler for a `role="radiogroup"` container whose tiles are
 * `role="radio"`. Arrows move focus and click the tile (radio semantics),
 * Home/End jump to the ends. Disabled tiles are skipped.
 */
export function onRadioGroupKeyDown(e: KeyboardEvent<HTMLElement>): void {
  moveRovingFocus(e, '[role="radio"]:not([disabled])', true);
}

/**
 * Arrow keys between `selector` items inside the container, focus only, for a
 * list of disclosure headers that should be one Tab stop.
 */
export function onRovingListKeyDown(e: KeyboardEvent<HTMLElement>, selector: string): void {
  moveRovingFocus(e, selector, false);
}

function moveRovingFocus(e: KeyboardEvent<HTMLElement>, selector: string, select: boolean): void {
  const keys = NEXT.has(e.key) || PREV.has(e.key) || e.key === 'Home' || e.key === 'End';
  if (!keys) return;
  const radios = [...e.currentTarget.querySelectorAll<HTMLElement>(selector)];
  if (radios.length === 0) return;
  const at = radios.indexOf(document.activeElement as HTMLElement);
  if (at < 0) return;
  e.preventDefault();
  const rtl = getComputedStyle(e.currentTarget).direction === 'rtl';
  let step = NEXT.has(e.key) ? 1 : -1;
  if (rtl && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) step = -step;
  const to =
    e.key === 'Home' ? 0 : e.key === 'End' ? radios.length - 1 : (at + step + radios.length) % radios.length;
  const target = radios[to];
  target?.focus();
  if (select) target?.click();
}

/** Tab index for tile `index`: only the selected tile (else the first) is in the Tab order. */
export function rovingTabIndex(isSelected: boolean, index: number, anySelected: boolean): 0 | -1 {
  return isSelected || (!anySelected && index === 0) ? 0 : -1;
}
