// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cell​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ addressing, range selection and keyboard movement for the BOQ sheet,
 * kept free of React so every key path is unit tested.
 */

export interface CellAddr {
  row: number;
  col: number;
}

export interface Selection {
  anchor: CellAddr;
  focus: CellAddr;
  /** Kept while Tab/Enter walk the active cell inside a selected range. */
  range?: Rect;
}

export interface Bounds {
  rows: number;
  cols: number;
}

export interface Rect {
  r0: number;
  r1: number;
  c0: number;
  c1: number;
}

export function rectOf(sel: Selection): Rect {
  if (sel.range) return sel.range;
  return {
    r0: Math.min(sel.anchor.row, sel.focus.row),
    r1: Math.max(sel.anchor.row, sel.focus.row),
    c0: Math.min(sel.anchor.col, sel.focus.col),
    c1: Math.max(sel.anchor.col, sel.focus.col),
  };
}

export function inRect(rect: Rect, row: number, col: number): boolean {
  return row >= rect.r0 && row <= rect.r1 && col >= rect.c0 && col <= rect.c1;
}

export function single(addr: CellAddr): Selection {
  return { anchor: addr, focus: addr };
}

function clamp(addr: CellAddr, b: Bounds): CellAddr {
  return {
    row: Math.max(0, Math.min(b.rows - 1, addr.row)),
    col: Math.max(0, Math.min(b.cols - 1, addr.col)),
  };
}

export interface KeyMods {
  shift?: boolean;
  ctrl?: boolean;
}

/**
 * Next selection after a navigation key, or null when the key does not move.
 * Arrows move (Shift extends, Ctrl jumps to the edge), Tab and Enter move the
 * active cell inside a multi-cell range like a spreadsheet, else step right/down.
 */
export function navigate(sel: Selection, key: string, mods: KeyMods, b: Bounds, pageRows = 20): Selection | null {
  if (b.rows === 0 || b.cols === 0) return null;
  const f = sel.focus;
  const step = (dr: number, dc: number): Selection => {
    const target = mods.ctrl
      ? clamp({ row: dr === 0 ? f.row : dr < 0 ? 0 : b.rows - 1, col: dc === 0 ? f.col : dc < 0 ? 0 : b.cols - 1 }, b)
      : clamp({ row: f.row + dr, col: f.col + dc }, b);
    return mods.shift ? { anchor: sel.anchor, focus: target } : single(target);
  };
  switch (key) {
    case 'ArrowUp':
      return step(-1, 0);
    case 'ArrowDown':
      return step(1, 0);
    case 'ArrowLeft':
      return step(0, -1);
    case 'ArrowRight':
      return step(0, 1);
    case 'PageDown':
      return step(pageRows, 0);
    case 'PageUp':
      return step(-pageRows, 0);
    case 'Home':
      return mods.ctrl ? single({ row: 0, col: 0 }) : single({ row: f.row, col: 0 });
    case 'End':
      return mods.ctrl ? single({ row: b.rows - 1, col: b.cols - 1 }) : single({ row: f.row, col: b.cols - 1 });
    case 'Tab':
    case 'Enter': {
      const rect = rectOf(sel);
      const multi = rect.r0 !== rect.r1 || rect.c0 !== rect.c1;
      const back = Boolean(mods.shift);
      if (!multi) {
        if (key === 'Tab') {
          let col = f.col + (back ? -1 : 1);
          let row = f.row;
          if (col >= b.cols) {
            col = 0;
            row = Math.min(b.rows - 1, row + 1);
          } else if (col < 0) {
            col = b.cols - 1;
            row = Math.max(0, row - 1);
          }
          return single({ row, col });
        }
        return single(clamp({ row: f.row + (back ? -1 : 1), col: f.col }, b));
      }
      // Inside a range the active cell walks the range and the range stays selected.
      let { row, col } = f;
      if (key === 'Tab') {
        col += back ? -1 : 1;
        if (col > rect.c1) {
          col = rect.c0;
          row = row >= rect.r1 ? rect.r0 : row + 1;
        } else if (col < rect.c0) {
          col = rect.c1;
          row = row <= rect.r0 ? rect.r1 : row - 1;
        }
      } else {
        row += back ? -1 : 1;
        if (row > rect.r1) {
          row = rect.r0;
          col = col >= rect.c1 ? rect.c0 : col + 1;
        } else if (row < rect.r0) {
          row = rect.r1;
          col = col <= rect.c0 ? rect.c1 : col - 1;
        }
      }
      return { anchor: sel.anchor, focus: { row, col }, range: rect };
    }
    default:
      return null;
  }
}

/** True when a printable key should start editing and overwrite the cell. */
export function isTypingKey(e: { key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean }): boolean {
  return e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey;
}
