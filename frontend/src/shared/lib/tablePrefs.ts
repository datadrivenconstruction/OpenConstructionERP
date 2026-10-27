// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Personal table options from Settings: spreadsheet-style tables and the
 * keyboard mode. Kept on this device and painted on <html> as
 * data-excel-tables / data-keyboard-mode so CSS and the table enhancer
 * (`tableEnhancer.ts`) can follow them without a re-render.
 */

export interface TablePrefs {
  /** Frozen header and first column, resize, sort, filter, totals, range copy. */
  excel: boolean;
  /** Arrow and Enter navigation in tables plus on-screen shortcut hints. */
  keyboard: boolean;
}

export const TABLE_PREFS_KEY = 'oe_table_prefs_v1';
export const TABLE_PREFS_EVENT = 'oe:table-prefs';
export const DEFAULT_TABLE_PREFS: TablePrefs = { excel: false, keyboard: false };

export function readTablePrefs(): TablePrefs {
  try {
    const raw = JSON.parse(localStorage.getItem(TABLE_PREFS_KEY) || 'null') as Partial<TablePrefs> | null;
    return {
      excel: raw?.excel === true,
      keyboard: raw?.keyboard === true,
    };
  } catch {
    return { ...DEFAULT_TABLE_PREFS };
  }
}

export function applyTablePrefs(p: TablePrefs, root: HTMLElement = document.documentElement): void {
  if (p.excel) root.dataset.excelTables = 'on';
  else delete root.dataset.excelTables;
  if (p.keyboard) root.dataset.keyboardMode = 'on';
  else delete root.dataset.keyboardMode;
}

export function writeTablePrefs(p: TablePrefs): void {
  try {
    localStorage.setItem(TABLE_PREFS_KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable: the choice still applies for this session */
  }
  if (typeof document === 'undefined') return;
  applyTablePrefs(p);
  window.dispatchEvent(new CustomEvent(TABLE_PREFS_EVENT, { detail: p }));
}
