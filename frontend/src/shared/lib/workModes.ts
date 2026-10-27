// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One-click work modes: each sets the whole bundle at once (interface style,
 * density, tables, menu and motion). Every setting stays editable afterwards;
 * a mode is only a starting point, not a lock.
 */
import { APPEARANCE_PRESETS, PLATFORM_APPEARANCE, type Appearance } from './appearance';
import { MENU_PRESETS, PLATFORM_MENU, type MenuLook } from './menuAppearance';
import { readComfort, writeComfort, type Motion } from './comfort';
import { writeTablePrefs, type TablePrefs } from './tablePrefs';

export const WORK_MODE_IDS = ['standard', 'classic', 'spreadsheet', 'field'] as const;
export type WorkModeId = (typeof WORK_MODE_IDS)[number];

export interface WorkMode {
  id: WorkModeId;
  appearance: Appearance;
  menu: MenuLook;
  tables: TablePrefs;
  motion: Motion;
}

const preset = (id: string): Appearance =>
  APPEARANCE_PRESETS.find((p) => p.id === id)?.value ?? PLATFORM_APPEARANCE;
const menuPreset = (id: string): MenuLook => MENU_PRESETS.find((p) => p.id === id)?.value ?? PLATFORM_MENU;

export const WORK_MODES: Record<WorkModeId, WorkMode> = {
  standard: {
    id: 'standard',
    appearance: PLATFORM_APPEARANCE,
    menu: PLATFORM_MENU,
    tables: { excel: false, keyboard: false },
    motion: 'full',
  },
  classic: {
    id: 'classic',
    appearance: preset('classic'),
    menu: { ...PLATFORM_MENU, stroke: 'light', active: 'bar', color: 'mono' },
    tables: { excel: false, keyboard: false },
    motion: 'reduced',
  },
  spreadsheet: {
    id: 'spreadsheet',
    appearance: { ...preset('classic'), density: 'compact' },
    menu: menuPreset('blueprint'),
    tables: { excel: true, keyboard: true },
    motion: 'reduced',
  },
  field: {
    id: 'field',
    appearance: { ...PLATFORM_APPEARANCE, density: 'comfortable', text: 'large' },
    menu: menuPreset('site_office'),
    tables: { excel: false, keyboard: false },
    motion: 'reduced',
  },
};

export interface WorkModeTargets {
  setAppearance: (value: Appearance) => void;
  setMenu: (value: MenuLook) => void;
}

/** Apply every part of a mode; the stores persist each part as usual. */
export function applyWorkMode(id: WorkModeId, targets: WorkModeTargets): void {
  const mode = WORK_MODES[id];
  targets.setAppearance(mode.appearance);
  targets.setMenu(mode.menu);
  writeTablePrefs(mode.tables);
  writeComfort({ ...readComfort(), motion: mode.motion });
}

/** The mode the current settings match exactly, or null for a custom mix. */
export function matchWorkMode(appearance: Appearance, menu: MenuLook, tables: TablePrefs): WorkModeId | null {
  const same = <T extends object>(a: T, b: T) =>
    (Object.keys(b) as (keyof T)[]).every((k) => a[k] === b[k]);
  for (const id of WORK_MODE_IDS) {
    const m = WORK_MODES[id];
    if (same(appearance, m.appearance) && same(menu, m.menu) && same(tables, m.tables)) return id;
  }
  return null;
}
