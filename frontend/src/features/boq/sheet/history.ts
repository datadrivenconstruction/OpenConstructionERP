// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Undo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ and redo for the BOQ sheet. One entry is one user action, however
 * many cells it touched (a paste, a fill, a replace-all), so Ctrl+Z reverts
 * the whole action at once.
 */

export type SheetField = 'ordinal' | 'description' | 'unit' | 'quantity' | 'unit_rate';

export interface CellChange {
  rowId: string;
  field: SheetField;
  before: string;
  after: string;
}

export function invert(batch: CellChange[]): CellChange[] {
  return batch.map((c) => ({ ...c, before: c.after, after: c.before })).reverse();
}

export class SheetHistory {
  private past: CellChange[][] = [];
  private future: CellChange[][] = [];

  constructor(private readonly limit = 200) {}

  push(batch: CellChange[]): void {
    const real = batch.filter((c) => c.before !== c.after);
    if (real.length === 0) return;
    this.past.push(real);
    if (this.past.length > this.limit) this.past.shift();
    this.future = [];
  }

  /** Changes that revert the last action, or null when there is nothing to undo. */
  undo(): CellChange[] | null {
    const last = this.past.pop();
    if (!last) return null;
    this.future.push(last);
    return invert(last);
  }

  redo(): CellChange[] | null {
    const next = this.future.pop();
    if (!next) return null;
    this.past.push(next);
    return next;
  }

  /** Put an action back after its write failed, so nothing is lost from the stack. */
  rollbackLast(direction: 'undo' | 'redo'): void {
    if (direction === 'undo') {
      const b = this.future.pop();
      if (b) this.past.push(b);
    } else {
      const b = this.past.pop();
      if (b) this.future.push(b);
    }
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }

  get canRedo(): boolean {
    return this.future.length > 0;
  }
}
