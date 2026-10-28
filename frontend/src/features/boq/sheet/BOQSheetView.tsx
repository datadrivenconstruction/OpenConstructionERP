// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Spreadsheet editing mode for a bill of quantities: keyboard-first cells,
 * range selection, clipboard to and from spreadsheets in the user's number
 * format, fill, undo across bulk edits, find and replace, cell formulas and
 * an outline by the bill's hierarchy. Rows are windowed and memoised, so an
 * edit repaints the touched rows only.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Columns3, Redo2, Search, Undo2 } from 'lucide-react';
import type { BOQVariable, Position } from '../api';
import type { PastedRow } from '../ExcelPasteModal';
import { extractReferences } from '../grid/formula';
import {
  dependencyInfo,
  positionsUsingVariable,
  variablesMap,
} from './cellFormula';
import {
  displayText,
  editText,
  hasFormula,
  isEditableCell,
  toSheetEdits,
  type CellError,
  type ColumnId,
  type SheetCellEdit,
} from './commit';
import { fillSeries } from './fill';
import { findAll, replaceAll, type Grid } from './findReplace';
import { buildOutline, groupsDeeperThan, levelKey, ordinalHeaderKey, visibleRows } from './hierarchy';
import { SheetHistory, type CellChange, type SheetField } from './history';
import { formatClipboardNumber, formatLocaleNumber, parseLocaleNumber } from './numberFormat';
import { buildPreview, type PreviewRow } from './pasteRows';
import { isTypingKey, navigate, rectOf, single, type Rect, type Selection } from './selection';
import { parseTSV, toTSV } from './tsv';

export const SHEET_ROW_HEIGHT = 28;
const OVERSCAN = 8;

export interface SheetCellIssue {
  severity: 'error' | 'warning' | 'info';
  message: string;
}

export interface BOQSheetViewProps {
  positions: Position[];
  locale: string;
  standard?: string | null;
  variables?: BOQVariable[];
  readOnly?: boolean;
  /** Failed validation rules per position id, shown in the row's cells. */
  issues?: ReadonlyMap<string, SheetCellIssue[]>;
  /** Writes one batch in one request; rejects to keep the old values. */
  onCommit: (edits: SheetCellEdit[]) => Promise<void>;
  onCreateRows: (rows: PastedRow[]) => Promise<void> | void;
  /** Visible height in px; the grid windows rows to it. */
  height?: number;
  /** Test hook: called on every row render. */
  onRowRender?: (rowId: string) => void;
}

interface ColumnDef {
  id: ColumnId;
  width: number;
  numeric: boolean;
}

const ALL_COLUMNS: ColumnDef[] = [
  { id: 'ordinal', width: 110, numeric: false },
  { id: 'description', width: 360, numeric: false },
  { id: 'unit', width: 70, numeric: false },
  { id: 'quantity', width: 110, numeric: true },
  { id: 'unit_rate', width: 110, numeric: true },
  { id: 'total', width: 130, numeric: true },
];

const HEADER_KEYS: Record<ColumnId, [string, string]> = {
  ordinal: ['boq.sheet.col_ordinal', 'Item'],
  description: ['boq.sheet.col_description', 'Description'],
  unit: ['boq.sheet.col_unit', 'Unit'],
  quantity: ['boq.sheet.col_quantity', 'Quantity'],
  unit_rate: ['boq.sheet.col_unit_rate', 'Unit rate'],
  total: ['boq.sheet.col_total', 'Total'],
};

interface EditState {
  row: number;
  col: number;
  draft: string;
}

interface RowProps {
  position: Position;
  rowIndex: number;
  level: number;
  hasChildren: boolean;
  collapsed: boolean;
  columns: ColumnDef[];
  leftOffsets: number[];
  frozen: number;
  locale: string;
  readOnly: boolean;
  /** Selected columns in this row as "c0:c1", or '' when the row is outside the range. */
  selSpan: string;
  /** Active column when the focus is in this row, else -1. */
  focusCol: number;
  editCol: number;
  draft: string;
  fillTarget: boolean;
  issueText: string;
  issueSeverity: '' | 'error' | 'warning' | 'info';
  cellErrors: string;
  onToggle: (id: string) => void;
  onDraft: (v: string) => void;
  onRowRender?: (rowId: string) => void;
  gridId: string;
}

const SheetRow = memo(function SheetRow(props: RowProps) {
  const { t } = useTranslation();
  const {
    position: p,
    rowIndex,
    columns,
    selSpan,
    focusCol,
    editCol,
    draft,
    locale,
    leftOffsets,
    frozen,
    issueSeverity,
    issueText,
    cellErrors,
  } = props;
  props.onRowRender?.(p.id);
  const [c0, c1] = selSpan ? selSpan.split(':').map(Number) : [-1, -2];
  const errors = cellErrors ? (JSON.parse(cellErrors) as Record<string, string>) : {};
  return (
    <div
      role="row"
      aria-rowindex={rowIndex + 2}
      className="flex border-b border-border-light"
      style={{ height: SHEET_ROW_HEIGHT }}
    >
      {columns.map((col, ci) => {
        const selected = ci >= c0! && ci <= c1!;
        const focused = ci === focusCol;
        const editing = ci === editCol;
        const editable = isEditableCell(p, col.id, props.readOnly);
        const err = errors[col.id];
        const issueHere = col.id === 'description' && issueSeverity;
        const style: CSSProperties = { width: col.width, minWidth: col.width };
        if (ci < frozen) {
          style.position = 'sticky';
          style.left = leftOffsets[ci];
          style.zIndex = 1;
        }
        const tone = err || issueHere === 'error'
          ? 'bg-semantic-error-bg/60'
          : issueHere === 'warning'
            ? 'bg-semantic-warning-bg/60'
            : selected
              ? 'bg-oe-blue/10'
              : 'bg-surface-primary';
        const title = err || (issueHere ? issueText : hasFormula(p, col.id) ? editText(p, col.id, locale) : undefined);
        return (
          <div
            key={col.id}
            id={`${props.gridId}-r${rowIndex}-c${ci}`}
            role="gridcell"
            aria-colindex={ci + 1}
            aria-selected={selected}
            aria-readonly={!editable}
            aria-invalid={Boolean(err) || issueHere === 'error' || undefined}
            data-row={rowIndex}
            data-col={ci}
            title={title}
            style={style}
            className={`relative truncate border-e border-border-light px-1.5 text-xs leading-[28px] ${tone} ${
              col.numeric ? 'text-end tabular-nums' : ''
            } ${focused ? 'outline outline-2 -outline-offset-2 outline-oe-blue' : ''} ${
              props.fillTarget && selected ? 'border-dashed' : ''
            } ${editable ? 'text-content-primary' : 'text-content-secondary'} ${
              p.unit === '' && col.id === 'description' ? 'font-semibold' : ''
            }`}
          >
            {editing ? (
              <input
                autoFocus
                aria-label={t(HEADER_KEYS[col.id][0], { defaultValue: HEADER_KEYS[col.id][1] })}
                className="absolute inset-0 w-full bg-surface-primary px-1.5 text-xs outline-none"
                value={draft}
                onChange={(e) => props.onDraft(e.target.value)}
                data-sheet-editor="1"
              />
            ) : (
              <>
                {col.id === 'ordinal' && (
                  <span style={{ paddingInlineStart: props.level * 12 }} className="inline-flex items-center">
                    {props.hasChildren ? (
                      <button
                        type="button"
                        tabIndex={-1}
                        aria-expanded={!props.collapsed}
                        aria-label={
                          props.collapsed
                            ? t('boq.sheet.expand_group', { defaultValue: 'Expand group' })
                            : t('boq.sheet.collapse_group', { defaultValue: 'Collapse group' })
                        }
                        onMouseDown={(e) => {
                          e.stopPropagation();
                          props.onToggle(p.id);
                        }}
                        className="me-0.5 text-content-tertiary hover:text-content-primary"
                      >
                        {props.collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
                      </button>
                    ) : null}
                  </span>
                )}
                {err ? <span className="font-semibold text-semantic-error">#!</span> : displayText(p, col.id, locale)}
                {hasFormula(p, col.id) && <span className="ms-1 text-2xs text-oe-blue">ƒ</span>}
                {focused && selected && selSpan && ci === c1 && (
                  <span
                    data-fill-handle="1"
                    aria-hidden
                    className="absolute bottom-0 end-0 h-2 w-2 cursor-crosshair bg-oe-blue"
                  />
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
});

function readStoredNumber(locale: string) {
  return (s: string) => parseLocaleNumber(s, locale);
}

export function BOQSheetView({
  positions,
  locale,
  standard,
  variables,
  readOnly = false,
  issues,
  onCommit,
  onCreateRows,
  height = 600,
  onRowRender,
}: BOQSheetViewProps) {
  const { t } = useTranslation();
  const gridId = useMemo(() => `boq-sheet-${Math.random().toString(36).slice(2, 8)}`, []);
  const containerRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef(new SheetHistory());
  const [, bumpHistory] = useState(0);
  const [hidden, setHidden] = useState<ReadonlySet<ColumnId>>(new Set());
  const [frozen, setFrozen] = useState(2);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [sel, setSel] = useState<Selection>(single({ row: 0, col: 0 }));
  const [edit, setEdit] = useState<EditState | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [fillTo, setFillTo] = useState<number | null>(null);
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [cellErrors, setCellErrors] = useState<Map<string, Record<string, string>>>(new Map());
  const [busy, setBusy] = useState(false);
  const [findOpen, setFindOpen] = useState<null | 'find' | 'replace'>(null);
  const [findText, setFindText] = useState('');
  const [replaceText, setReplaceText] = useState('');
  const [findHint, setFindHint] = useState('');
  const [chooserOpen, setChooserOpen] = useState(false);
  const dragRef = useRef<'select' | 'fill' | null>(null);

  const varMap = useMemo(() => variablesMap(variables), [variables]);
  const outline = useMemo(() => buildOutline(positions), [positions]);
  const rows = useMemo(() => visibleRows(outline, collapsed), [outline, collapsed]);
  const columns = useMemo(() => ALL_COLUMNS.filter((c) => !hidden.has(c.id)), [hidden]);
  const leftOffsets = useMemo(() => {
    const out: number[] = [];
    let x = 0;
    for (const c of columns) {
      out.push(x);
      x += c.width;
    }
    return out;
  }, [columns]);
  const bounds = useMemo(() => ({ rows: rows.length, cols: columns.length }), [rows.length, columns.length]);
  const rect = rectOf(sel);

  const first = Math.max(0, Math.floor(scrollTop / SHEET_ROW_HEIGHT) - OVERSCAN);
  const last = Math.min(rows.length, Math.ceil((scrollTop + height) / SHEET_ROW_HEIGHT) + OVERSCAN);

  const textAt = useCallback(
    (r: number, c: number) => {
      const row = rows[r];
      const col = columns[c];
      return row && col ? editText(row.position, col.id, locale) : '';
    },
    [rows, columns, locale],
  );

  /* ── Writing ───────────────────────────────────────────────────────── */

  const write = useCallback(
    async (changes: CellChange[], record: 'push' | 'undo' | 'redo' = 'push') => {
      const real = changes.filter((c) => c.before !== c.after);
      if (real.length === 0) return true;
      const { edits, errors } = toSheetEdits(real, positions, varMap, locale);
      const errMap = new Map<string, Record<string, string>>();
      for (const e of errors) errMap.set(e.rowId, { ...(errMap.get(e.rowId) ?? {}), [e.field]: errorText(e) });
      setCellErrors(errMap);
      if (edits.length === 0) return errors.length === 0;
      setBusy(true);
      try {
        await onCommit(edits);
        if (record === 'push') historyRef.current.push(real.filter((c) => !errMap.get(c.rowId)?.[c.field]));
        bumpHistory((n) => n + 1);
        return true;
      } catch {
        if (record !== 'push') historyRef.current.rollbackLast(record);
        return false;
      } finally {
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [positions, varMap, locale, onCommit],
  );

  function errorText(e: CellError): string {
    const o = e.outcome;
    if (o.error === 'cycle') {
      return t('boq.sheet.err_cycle', {
        defaultValue: 'Circular reference: {{path}}',
        path: (o as { cycle: string[] }).cycle.join(' → '),
      });
    }
    if (o.error === 'negative') return t('boq.sheet.err_negative', { defaultValue: 'Negative values are not allowed' });
    if (o.error === 'not_a_number') return t('boq.sheet.err_number', { defaultValue: 'Not a number' });
    return t('boq.sheet.err_formula', { defaultValue: 'The formula cannot be evaluated' });
  }

  const changeFor = useCallback(
    (r: number, c: number, after: string): CellChange | null => {
      const row = rows[r];
      const col = columns[c];
      if (!row || !col || col.id === 'total' || !isEditableCell(row.position, col.id, readOnly)) return null;
      return { rowId: row.position.id, field: col.id as SheetField, before: editText(row.position, col.id, locale), after };
    },
    [rows, columns, readOnly, locale],
  );

  const focusGrid = () => containerRef.current?.focus();

  const commitEdit = useCallback(async () => {
    if (!edit) return;
    const ch = changeFor(edit.row, edit.col, edit.draft);
    setEdit(null);
    focusGrid();
    if (ch) await write([ch]);
  }, [edit, changeFor, write]);

  /* ── Clipboard ─────────────────────────────────────────────────────── */

  const copyText = useCallback(() => {
    const matrix: string[][] = [];
    for (let r = rect.r0; r <= rect.r1; r += 1) {
      const line: string[] = [];
      for (let c = rect.c0; c <= rect.c1; c += 1) {
        const row = rows[r];
        const col = columns[c];
        if (!row || !col) continue;
        const p = row.position;
        line.push(col.numeric ? formatClipboardNumber(Number(p[col.id as 'quantity'] ?? 0), locale) : textAt(r, c));
      }
      matrix.push(line);
    }
    return toTSV(matrix);
  }, [rect.r0, rect.r1, rect.c0, rect.c1, rows, columns, locale, textAt]);

  const pasteMatrix = useCallback(
    async (matrix: string[][]) => {
      if (readOnly || matrix.length === 0) return;
      const changes: CellChange[] = [];
      const multi = rect.r0 !== rect.r1 || rect.c0 !== rect.c1;
      // One copied value pasted onto a range fills the range, as spreadsheets do.
      if (matrix.length === 1 && matrix[0]!.length === 1 && multi) {
        for (let r = rect.r0; r <= rect.r1; r += 1)
          for (let c = rect.c0; c <= rect.c1; c += 1) {
            const ch = changeFor(r, c, matrix[0]![0]!);
            if (ch) changes.push(ch);
          }
        await write(changes);
        return;
      }
      const overflow: string[][] = [];
      matrix.forEach((line, dr) => {
        const r = rect.r0 + dr;
        if (r >= rows.length) {
          overflow.push(line);
          return;
        }
        line.forEach((val, dc) => {
          const ch = changeFor(r, rect.c0 + dc, val);
          if (ch) changes.push(ch);
        });
      });
      await write(changes);
      if (overflow.length > 0) {
        const fields = columns.slice(rect.c0).map((c) => c.id).filter((id): id is SheetField => id !== 'total');
        setPreview(buildPreview(overflow, fields, locale));
      }
    },
    [readOnly, rect.r0, rect.r1, rect.c0, rect.c1, rows.length, columns, changeFor, write, locale],
  );

  /* ── Fill ──────────────────────────────────────────────────────────── */

  const fillRange = useCallback(
    async (r0: number, r1: number, toRow: number) => {
      const parse = readStoredNumber(locale);
      const changes: CellChange[] = [];
      for (let c = rect.c0; c <= rect.c1; c += 1) {
        const seeds: string[] = [];
        for (let r = r0; r <= r1; r += 1) seeds.push(textAt(r, c));
        const numeric = columns[c]?.numeric ?? false;
        const values = fillSeries(seeds, toRow - r1, numeric ? parse : () => null, (n) =>
          formatLocaleNumber(n, locale, 6).replace(/[\s  ]/g, ''),
        );
        values.forEach((v, i) => {
          const ch = changeFor(r1 + 1 + i, c, v);
          if (ch) changes.push(ch);
        });
      }
      await write(changes);
    },
    [locale, rect.c0, rect.c1, columns, textAt, changeFor, write],
  );

  const fillDown = useCallback(async () => {
    const changes: CellChange[] = [];
    const top = rect.r0 === rect.r1 ? rect.r0 - 1 : rect.r0;
    if (top < 0) return;
    for (let r = top + 1; r <= rect.r1; r += 1)
      for (let c = rect.c0; c <= rect.c1; c += 1) {
        const ch = changeFor(r, c, textAt(top, c));
        if (ch) changes.push(ch);
      }
    await write(changes);
  }, [rect.r0, rect.r1, rect.c0, rect.c1, changeFor, textAt, write]);

  /* ── Undo / redo ───────────────────────────────────────────────────── */

  const undo = useCallback(async () => {
    const batch = historyRef.current.undo();
    if (batch) await write(batch, 'undo');
    bumpHistory((n) => n + 1);
  }, [write]);

  const redo = useCallback(async () => {
    const batch = historyRef.current.redo();
    if (batch) await write(batch, 'redo');
    bumpHistory((n) => n + 1);
  }, [write]);

  /* ── Find / replace ────────────────────────────────────────────────── */

  const gridModel: Grid = useMemo(
    () => ({
      rowIds: rows.map((r) => r.position.id),
      fields: columns.map((c) => c.id as SheetField),
      text: textAt,
      editable: (r, c) => {
        const row = rows[r];
        const col = columns[c];
        return Boolean(row && col && isEditableCell(row.position, col.id, readOnly));
      },
    }),
    [rows, columns, textAt, readOnly],
  );

  const findScope = (): Rect =>
    rect.r0 !== rect.r1 || rect.c0 !== rect.c1
      ? rect
      : { r0: 0, r1: Math.max(0, rows.length - 1), c0: 0, c1: Math.max(0, columns.length - 1) };

  const findNext = () => {
    const hits = findAll(gridModel, findText, findScope());
    if (hits.length === 0) {
      setFindHint(t('boq.sheet.find_none', { defaultValue: 'No matches' }));
      return;
    }
    const f = sel.focus;
    const next = hits.find((h) => h.row > f.row || (h.row === f.row && h.col > f.col)) ?? hits[0]!;
    setSel(single(next));
    scrollToRow(next.row);
    setFindHint(t('boq.sheet.find_count', { defaultValue: 'Matches: {{count}}', count: hits.length }));
  };

  const doReplaceAll = async () => {
    const { changes, skipped } = replaceAll(gridModel, findText, replaceText, findScope());
    await write(changes);
    setFindHint(
      t('boq.sheet.replace_done', {
        defaultValue: 'Cells replaced: {{count}}, read-only cells skipped: {{skipped}}',
        count: changes.length,
        skipped,
      }),
    );
  };

  /* ── Scrolling ─────────────────────────────────────────────────────── */

  const scrollToRow = (r: number) => {
    const el = containerRef.current;
    if (!el) return;
    const top = r * SHEET_ROW_HEIGHT;
    if (top < el.scrollTop) el.scrollTop = top;
    else if (top + SHEET_ROW_HEIGHT * 2 > el.scrollTop + height) el.scrollTop = top - height + SHEET_ROW_HEIGHT * 2;
    setScrollTop(el.scrollTop);
  };

  useEffect(() => {
    if (sel.focus.row >= rows.length && rows.length > 0) setSel(single({ row: rows.length - 1, col: sel.focus.col }));
  }, [rows.length, sel.focus.row, sel.focus.col]);

  const setDraft = useCallback((v: string) => setEdit((s) => (s ? { ...s, draft: v } : s)), []);

  const toggleGroup = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  /* ── Keyboard ──────────────────────────────────────────────────────── */

  const onKeyDown = async (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const ctrl = e.ctrlKey || e.metaKey;
    if (edit) {
      if (e.key === 'Escape') {
        e.preventDefault();
        setEdit(null);
        focusGrid();
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        await commitEdit();
        const moved = navigate(sel, e.key, { shift: e.shiftKey }, bounds);
        if (moved) setSel(moved);
      }
      return;
    }
    const key = e.key.toLowerCase();
    if (ctrl && key === 'z' && !e.shiftKey) {
      e.preventDefault();
      await undo();
      return;
    }
    if (ctrl && (key === 'y' || (key === 'z' && e.shiftKey))) {
      e.preventDefault();
      await redo();
      return;
    }
    if (ctrl && key === 'd') {
      e.preventDefault();
      await fillDown();
      return;
    }
    if (ctrl && (key === 'f' || key === 'h')) {
      e.preventDefault();
      setFindOpen(key === 'h' ? 'replace' : 'find');
      return;
    }
    if (ctrl && key === 'a') {
      e.preventDefault();
      setSel({ anchor: { row: 0, col: 0 }, focus: { row: bounds.rows - 1, col: bounds.cols - 1 } });
      return;
    }
    if (e.altKey && e.shiftKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      const row = rows[sel.focus.row];
      if (row?.hasChildren) {
        e.preventDefault();
        const isCollapsed = collapsed.has(row.position.id);
        if ((e.key === 'ArrowLeft') !== isCollapsed) toggleGroup(row.position.id);
      }
      return;
    }
    if (e.key === 'F2') {
      e.preventDefault();
      const ch = changeFor(sel.focus.row, sel.focus.col, '');
      if (ch) setEdit({ row: sel.focus.row, col: sel.focus.col, draft: ch.before });
      return;
    }
    if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      const changes: CellChange[] = [];
      for (let r = rect.r0; r <= rect.r1; r += 1)
        for (let c = rect.c0; c <= rect.c1; c += 1) {
          const ch = changeFor(r, c, '');
          if (ch) changes.push(ch);
        }
      await write(changes);
      return;
    }
    const moved = navigate(sel, e.key, { shift: e.shiftKey, ctrl }, bounds, Math.floor(height / SHEET_ROW_HEIGHT));
    if (moved) {
      e.preventDefault();
      setSel(moved);
      scrollToRow(moved.focus.row);
      return;
    }
    if (isTypingKey(e) && changeFor(sel.focus.row, sel.focus.col, '')) {
      e.preventDefault();
      setEdit({ row: sel.focus.row, col: sel.focus.col, draft: e.key });
    }
  };

  /* ── Mouse ─────────────────────────────────────────────────────────── */

  const cellFromEvent = (target: EventTarget | null): { row: number; col: number } | null => {
    const el = (target as HTMLElement | null)?.closest?.('[data-row]') as HTMLElement | null;
    if (!el) return null;
    return { row: Number(el.dataset.row), col: Number(el.dataset.col) };
  };

  const onMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).dataset?.sheetEditor) return;
    if ((e.target as HTMLElement).dataset?.fillHandle) {
      e.preventDefault();
      dragRef.current = 'fill';
      setFillTo(rect.r1);
      return;
    }
    const addr = cellFromEvent(e.target);
    if (!addr) return;
    if (edit) void commitEdit();
    e.preventDefault();
    focusGrid();
    dragRef.current = 'select';
    setSel(e.shiftKey ? { anchor: sel.anchor, focus: addr } : single(addr));
  };

  const onMouseOver = (e: React.MouseEvent) => {
    if (!dragRef.current) return;
    const addr = cellFromEvent(e.target);
    if (!addr) return;
    if (dragRef.current === 'select') setSel((s) => ({ anchor: s.anchor, focus: addr }));
    else setFillTo(Math.max(rect.r1, addr.row));
  };

  useEffect(() => {
    const up = () => {
      if (dragRef.current === 'fill' && fillTo !== null && fillTo > rect.r1) {
        void fillRange(rect.r0, rect.r1, fillTo).then(() =>
          setSel({ anchor: { row: rect.r0, col: rect.c0 }, focus: { row: fillTo, col: rect.c1 } }),
        );
      }
      dragRef.current = null;
      setFillTo(null);
    };
    window.addEventListener('mouseup', up);
    return () => window.removeEventListener('mouseup', up);
  }, [fillTo, rect.r0, rect.r1, rect.c0, rect.c1, fillRange]);

  /* ── Status bar: formula, dependencies, variable audit ─────────────── */

  const focusRow = rows[sel.focus.row];
  const focusColDef = columns[sel.focus.col];
  const status = useMemo(() => {
    if (!focusRow || !focusColDef) return null;
    const p = focusRow.position;
    const formula = hasFormula(p, focusColDef.id) ? editText(p, focusColDef.id, locale) : '';
    const deps = formula || focusColDef.id === 'quantity' || focusColDef.id === 'unit_rate' ? dependencyInfo(p.id, positions) : null;
    const vars: string[] = formula ? [...extractReferences(formula).variables] : [];
    const audit = vars.map((v) => ({ name: v, users: positionsUsingVariable(v, positions).length }));
    return { formula, deps, audit, issue: issues?.get(p.id) ?? [] };
  }, [focusRow, focusColDef, positions, locale, issues]);

  /* ── Render ────────────────────────────────────────────────────────── */

  const totalWidth = columns.reduce((s, c) => s + c.width, 0);
  const fillRect = fillTo !== null && fillTo > rect.r1 ? { ...rect, r1: fillTo } : null;

  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid="boq-sheet">
      <div className="flex flex-wrap items-center gap-2 text-xs" role="toolbar" aria-label={t('boq.sheet.toolbar', { defaultValue: 'Sheet tools' })}>
        <button
          type="button"
          onClick={() => void undo()}
          disabled={!historyRef.current.canUndo || busy}
          className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-0.5 disabled:opacity-40"
          aria-label={t('boq.sheet.undo', { defaultValue: 'Undo' })}
        >
          <Undo2 size={13} />
        </button>
        <button
          type="button"
          onClick={() => void redo()}
          disabled={!historyRef.current.canRedo || busy}
          className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-0.5 disabled:opacity-40"
          aria-label={t('boq.sheet.redo', { defaultValue: 'Redo' })}
        >
          <Redo2 size={13} />
        </button>
        <button
          type="button"
          onClick={() => setFindOpen(findOpen ? null : 'replace')}
          className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-0.5"
        >
          <Search size={13} />
          {t('boq.sheet.find_replace', { defaultValue: 'Find and replace' })}
        </button>
        <div className="relative">
          <button
            type="button"
            aria-expanded={chooserOpen}
            onClick={() => setChooserOpen((v) => !v)}
            className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-0.5"
          >
            <Columns3 size={13} />
            {t('boq.sheet.columns', { defaultValue: 'Columns' })}
          </button>
          {chooserOpen && (
            <div className="absolute z-20 mt-1 w-48 rounded-md border border-border-light bg-surface-primary p-2 shadow-lg">
              {ALL_COLUMNS.filter((c) => c.id !== 'description').map((c) => (
                <label key={c.id} className="flex items-center gap-2 py-0.5">
                  <input
                    type="checkbox"
                    checked={!hidden.has(c.id)}
                    onChange={() =>
                      setHidden((prev) => {
                        const next = new Set(prev);
                        if (next.has(c.id)) next.delete(c.id);
                        else next.add(c.id);
                        return next;
                      })
                    }
                  />
                  {c.id === 'ordinal'
                    ? t(ordinalHeaderKey(standard), { defaultValue: HEADER_KEYS.ordinal[1] })
                    : t(HEADER_KEYS[c.id][0], { defaultValue: HEADER_KEYS[c.id][1] })}
                </label>
              ))}
            </div>
          )}
        </div>
        <label className="inline-flex items-center gap-1">
          {t('boq.sheet.freeze', { defaultValue: 'Freeze columns' })}
          <select
            value={frozen}
            onChange={(e) => setFrozen(Number(e.target.value))}
            className="rounded border border-border-light bg-surface-primary px-1 py-0.5"
          >
            {[0, 1, 2, 3].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <span className="inline-flex items-center gap-1">
          {t('boq.sheet.outline', { defaultValue: 'Outline' })}
          {[1, 2, 3].map((lvl) => (
            <button
              key={lvl}
              type="button"
              title={t(levelKey(standard, lvl - 1), { defaultValue: `Level ${lvl}` })}
              onClick={() => setCollapsed(groupsDeeperThan(outline, lvl - 1))}
              className="rounded border border-border-light px-1.5 py-0.5 tabular-nums"
            >
              {lvl}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setCollapsed(new Set())}
            className="rounded border border-border-light px-1.5 py-0.5"
          >
            {t('boq.sheet.expand_all', { defaultValue: 'Expand all' })}
          </button>
        </span>
        {busy && <span className="text-content-tertiary">{t('boq.sheet.saving', { defaultValue: 'Saving…' })}</span>}
      </div>

      {findOpen && (
        <div className="flex flex-wrap items-center gap-2 text-xs" role="search">
          <input
            autoFocus
            value={findText}
            onChange={(e) => setFindText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') findNext();
              if (e.key === 'Escape') {
                setFindOpen(null);
                focusGrid();
              }
            }}
            aria-label={t('boq.sheet.find', { defaultValue: 'Find' })}
            placeholder={t('boq.sheet.find', { defaultValue: 'Find' })}
            className="h-7 w-44 rounded-md border border-border-light bg-surface-primary px-2"
          />
          <input
            value={replaceText}
            onChange={(e) => setReplaceText(e.target.value)}
            aria-label={t('boq.sheet.replace_with', { defaultValue: 'Replace with' })}
            placeholder={t('boq.sheet.replace_with', { defaultValue: 'Replace with' })}
            className="h-7 w-44 rounded-md border border-border-light bg-surface-primary px-2"
          />
          <button type="button" onClick={findNext} className="rounded border border-border-light px-2 py-0.5">
            {t('boq.sheet.find_next', { defaultValue: 'Find next' })}
          </button>
          <button
            type="button"
            disabled={readOnly || !findText}
            onClick={() => void doReplaceAll()}
            className="rounded border border-border-light px-2 py-0.5 disabled:opacity-40"
          >
            {t('boq.sheet.replace_all', { defaultValue: 'Replace all' })}
          </button>
          <span className="text-content-tertiary" aria-live="polite">
            {rect.r0 !== rect.r1 || rect.c0 !== rect.c1
              ? t('boq.sheet.scope_selection', { defaultValue: 'In selection' })
              : t('boq.sheet.scope_all', { defaultValue: 'In the whole bill' })}
            {findHint ? ` · ${findHint}` : ''}
          </span>
        </div>
      )}

      <div
        ref={containerRef}
        role="grid"
        aria-label={t('boq.sheet.grid_label', { defaultValue: 'Bill of quantities, spreadsheet mode' })}
        aria-rowcount={rows.length + 1}
        aria-colcount={columns.length}
        aria-multiselectable
        aria-readonly={readOnly || undefined}
        aria-activedescendant={`${gridId}-r${sel.focus.row}-c${sel.focus.col}`}
        tabIndex={0}
        onKeyDown={(e) => void onKeyDown(e)}
        onCopy={(e) => {
          if (edit) return;
          e.preventDefault();
          e.clipboardData.setData('text/plain', copyText());
        }}
        onCut={(e) => {
          if (edit || readOnly) return;
          e.preventDefault();
          e.clipboardData.setData('text/plain', copyText());
          void onKeyDown({ key: 'Delete', preventDefault() {} } as unknown as ReactKeyboardEvent<HTMLDivElement>);
        }}
        onPaste={(e) => {
          if (edit) return;
          e.preventDefault();
          void pasteMatrix(parseTSV(e.clipboardData.getData('text/plain')));
        }}
        onMouseDown={onMouseDown}
        onMouseOver={onMouseOver}
        onDoubleClick={(e) => {
          const addr = cellFromEvent(e.target);
          const ch = addr && changeFor(addr.row, addr.col, '');
          if (addr && ch) setEdit({ row: addr.row, col: addr.col, draft: ch.before });
        }}
        onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        className="relative overflow-auto rounded-lg border border-border-light bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        style={{ height }}
      >
        <div style={{ width: totalWidth }}>
          <div role="row" aria-rowindex={1} className="sticky top-0 z-10 flex border-b border-border-light bg-surface-secondary">
            {columns.map((c, ci) => (
              <div
                key={c.id}
                role="columnheader"
                aria-colindex={ci + 1}
                style={{
                  width: c.width,
                  minWidth: c.width,
                  ...(ci < frozen ? { position: 'sticky', left: leftOffsets[ci], zIndex: 2 } : {}),
                }}
                className={`truncate border-e border-border-light bg-surface-secondary px-1.5 py-1 text-2xs font-semibold uppercase text-content-tertiary ${
                  c.numeric ? 'text-end' : ''
                }`}
              >
                {c.id === 'ordinal'
                  ? t(ordinalHeaderKey(standard), { defaultValue: HEADER_KEYS.ordinal[1] })
                  : t(HEADER_KEYS[c.id][0], { defaultValue: HEADER_KEYS[c.id][1] })}
              </div>
            ))}
          </div>
          <div style={{ height: first * SHEET_ROW_HEIGHT }} />
          {rows.slice(first, last).map((r, i) => {
            const ri = first + i;
            const paint = fillRect ?? rect;
            const inRange = ri >= paint.r0 && ri <= paint.r1;
            const rowIssues = issues?.get(r.position.id) ?? [];
            const sev = rowIssues.some((x) => x.severity === 'error')
              ? 'error'
              : rowIssues.some((x) => x.severity === 'warning')
                ? 'warning'
                : r.position.validation_status === 'errors'
                  ? 'error'
                  : r.position.validation_status === 'warnings'
                    ? 'warning'
                    : '';
            const errs = cellErrors.get(r.position.id);
            return (
              <SheetRow
                key={r.position.id}
                position={r.position}
                rowIndex={ri}
                level={r.level}
                hasChildren={r.hasChildren}
                collapsed={collapsed.has(r.position.id)}
                columns={columns}
                leftOffsets={leftOffsets}
                frozen={frozen}
                locale={locale}
                readOnly={readOnly}
                selSpan={inRange ? `${paint.c0}:${paint.c1}` : ''}
                focusCol={sel.focus.row === ri ? sel.focus.col : -1}
                editCol={edit?.row === ri ? edit.col : -1}
                draft={edit?.row === ri ? edit.draft : ''}
                fillTarget={fillRect !== null && inRange && ri > rect.r1}
                issueText={rowIssues.map((x) => x.message).join('\n')}
                issueSeverity={sev}
                cellErrors={errs ? JSON.stringify(errs) : ''}
                onToggle={toggleGroup}
                onDraft={setDraft}
                onRowRender={onRowRender}
                gridId={gridId}
              />
            );
          })}
          <div style={{ height: Math.max(0, rows.length - last) * SHEET_ROW_HEIGHT }} />
        </div>
      </div>

      <div className="flex min-h-[20px] flex-wrap items-center gap-3 text-2xs text-content-tertiary" aria-live="polite">
        {status?.formula && <span className="font-mono text-content-secondary">{status.formula}</span>}
        {status?.deps && status.deps.uses.length > 0 && (
          <span>{t('boq.sheet.uses', { defaultValue: 'Uses: {{list}}', list: status.deps.uses.join(', ') })}</span>
        )}
        {status?.deps && status.deps.usedBy.length > 0 && (
          <span>{t('boq.sheet.used_by', { defaultValue: 'Used by: {{list}}', list: status.deps.usedBy.join(', ') })}</span>
        )}
        {status?.audit.map((a) => (
          <span key={a.name}>
            {t('boq.sheet.variable_users', {
              defaultValue: '{{name}} is used by positions: {{count}}',
              name: `$${a.name}`,
              count: a.users,
            })}
          </span>
        ))}
        {status?.issue.map((x, i) => (
          <span key={i} className={x.severity === 'error' ? 'text-semantic-error' : 'text-semantic-warning'}>
            {x.message}
          </span>
        ))}
        <span className="ms-auto">
          {t('boq.sheet.hint', {
            defaultValue: 'Arrows move, Enter or F2 edits, Esc cancels, Ctrl+D fills down, Ctrl+Z undoes',
          })}
        </span>
      </div>

      {preview && (
        <PastePreview
          rows={preview}
          locale={locale}
          onCancel={() => setPreview(null)}
          onConfirm={async (ok) => {
            await onCreateRows(ok);
            setPreview(null);
          }}
        />
      )}
    </div>
  );
}

function PastePreview({
  rows,
  locale,
  onCancel,
  onConfirm,
}: {
  rows: PreviewRow[];
  locale: string;
  onCancel: () => void;
  onConfirm: (rows: PastedRow[]) => Promise<void>;
}) {
  const { t } = useTranslation();
  const valid = rows.filter((r) => r.issues.length === 0).map((r) => r.row);
  const issueLabel = (code: string) =>
    t(`boq.sheet.issue_${code}`, {
      defaultValue:
        code === 'description_missing'
          ? 'Description is missing'
          : code === 'unit_missing'
            ? 'Unit is missing'
            : code === 'negative'
              ? 'Negative value'
              : 'Not a number',
    });
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="boq-sheet-preview-title" className="rounded-lg border border-border-light bg-surface-primary p-3 shadow-lg">
      <h3 id="boq-sheet-preview-title" className="mb-2 text-sm font-semibold">
        {t('boq.sheet.preview_title', { defaultValue: 'New positions to create: {{count}}', count: valid.length })}
      </h3>
      <div className="max-h-64 overflow-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-start text-content-tertiary">
              <th className="text-start">{t('boq.sheet.col_ordinal', { defaultValue: 'Item' })}</th>
              <th className="text-start">{t('boq.sheet.col_description', { defaultValue: 'Description' })}</th>
              <th className="text-start">{t('boq.sheet.col_unit', { defaultValue: 'Unit' })}</th>
              <th className="text-end">{t('boq.sheet.col_quantity', { defaultValue: 'Quantity' })}</th>
              <th className="text-end">{t('boq.sheet.col_unit_rate', { defaultValue: 'Unit rate' })}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={r.issues.length ? 'bg-semantic-error-bg/50' : ''}>
                <td>{r.row.ordinal}</td>
                <td>{r.row.description}</td>
                <td>{r.row.unit}</td>
                <td className="text-end tabular-nums">{formatLocaleNumber(r.row.quantity, locale, 3)}</td>
                <td className="text-end tabular-nums">{formatLocaleNumber(r.row.unit_rate, locale, 2, 2)}</td>
                <td className="text-semantic-error">{r.issues.map((x) => issueLabel(x.code)).join('; ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex justify-end gap-2 text-xs">
        <button type="button" onClick={onCancel} className="rounded border border-border-light px-3 py-1">
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </button>
        <button
          type="button"
          disabled={valid.length === 0}
          onClick={() => void onConfirm(valid)}
          className="rounded bg-oe-blue px-3 py-1 text-white disabled:opacity-40"
        >
          {t('boq.sheet.preview_confirm', { defaultValue: 'Create positions' })}
        </button>
      </div>
    </div>
  );
}

