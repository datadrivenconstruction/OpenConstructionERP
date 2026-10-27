// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sheet​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ logic: locale numbers, clipboard text, keys, fill, undo, find, formulas.
 */
import { describe, expect, it } from 'vitest';
import type { Position } from '../../api';
import { dependencyInfo, evaluateCellFormula, positionsUsingVariable } from '../cellFormula';
import { editText, toSheetEdits } from '../commit';
import { fillSeries } from '../fill';
import { findAll, replaceAll, type Grid } from '../findReplace';
import { buildOutline, levelKey, ordinalHeaderKey, visibleRows } from '../hierarchy';
import { SheetHistory } from '../history';
import { formatClipboardNumber, parseLocaleNumber } from '../numberFormat';
import { buildPreview } from '../pasteRows';
import { navigate, rectOf, single } from '../selection';
import { parseTSV, toTSV } from '../tsv';

function pos(id: string, ordinal: string, over: Partial<Position> = {}): Position {
  return {
    id,
    boq_id: 'b',
    parent_id: null,
    ordinal,
    description: `Item ${ordinal}`,
    unit: 'm2',
    quantity: 1,
    unit_rate: 10,
    total: 10,
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: 0,
    validation_status: 'pending',
    metadata: {},
    version: 0,
    ...over,
  } as Position;
}

describe('locale numbers', () => {
  it.each([
    ['1.234,56', 'de-DE', 1234.56],
    ['1234,56', 'de-DE', 1234.56],
    ['12.5', 'de-DE', 12.5],
    ['1,234.56', 'en-US', 1234.56],
    ['1,5', 'en-US', 1.5],
    ['1 234,56', 'fr-FR', 1234.56],
    ['1 234,56', 'fr-FR', 1234.56],
    ["1'234.56", 'de-CH', 1234.56],
    ['12,34,567.5', 'en-IN', 1234567.5],
    ['€ 99,90', 'de-DE', 99.9],
  ])('reads %s in %s', (raw, locale, expected) => {
    expect(parseLocaleNumber(raw, locale)).toBeCloseTo(expected, 6);
  });

  it('refuses text and broken groups', () => {
    expect(parseLocaleNumber('abc', 'en-US')).toBeNull();
    expect(parseLocaleNumber('1.2.3', 'de-DE')).toBeNull();
  });

  it('writes the clipboard with the locale decimal and no grouping', () => {
    expect(formatClipboardNumber(1234.56, 'de-DE')).toBe('1234,56');
    expect(formatClipboardNumber(1234.56, 'en-US')).toBe('1234.56');
  });
});

describe('TSV', () => {
  it('round-trips quotes, tabs and line breaks', () => {
    const m = [
      ['a', 'b\tc'],
      ['line\nbreak', 'say "hi"'],
    ];
    expect(parseTSV(toTSV(m))).toEqual(m);
  });

  it('reads spreadsheet output with CRLF and a trailing newline', () => {
    expect(parseTSV('01\tWall\tm2\t1,5\r\n02\tSlab\tm3\t2\r\n')).toEqual([
      ['01', 'Wall', 'm2', '1,5'],
      ['02', 'Slab', 'm3', '2'],
    ]);
  });
});

describe('keyboard', () => {
  const b = { rows: 10, cols: 5 };
  it('moves with arrows and extends with Shift', () => {
    expect(navigate(single({ row: 2, col: 2 }), 'ArrowDown', {}, b)!.focus).toEqual({ row: 3, col: 2 });
    const ext = navigate(single({ row: 2, col: 2 }), 'ArrowRight', { shift: true }, b)!;
    expect(rectOf(ext)).toEqual({ r0: 2, r1: 2, c0: 2, c1: 3 });
  });

  it('jumps to the edge with Ctrl and clamps at the border', () => {
    expect(navigate(single({ row: 2, col: 2 }), 'ArrowDown', { ctrl: true }, b)!.focus.row).toBe(9);
    expect(navigate(single({ row: 0, col: 0 }), 'ArrowUp', {}, b)!.focus).toEqual({ row: 0, col: 0 });
  });

  it('wraps Tab to the next row and walks Enter inside a range', () => {
    expect(navigate(single({ row: 1, col: 4 }), 'Tab', {}, b)!.focus).toEqual({ row: 2, col: 0 });
    const range = { anchor: { row: 0, col: 0 }, focus: { row: 1, col: 1 } };
    const start = { anchor: range.anchor, focus: { row: 1, col: 0 }, range: rectOf(range) };
    const next = navigate(start, 'Enter', {}, b)!;
    expect(next.focus).toEqual({ row: 0, col: 1 });
    expect(rectOf(next)).toEqual({ r0: 0, r1: 1, c0: 0, c1: 1 });
  });
});

describe('fill', () => {
  const de = (s: string) => parseLocaleNumber(s, 'de-DE');
  const fmt = (n: number) => String(n).replace('.', ',');
  it('continues a numeric step in the user locale', () => {
    expect(fillSeries(['1,5', '2'], 3, de, fmt)).toEqual(['2,5', '3', '3,5']);
  });
  it('counts on an ordinal and keeps its padding', () => {
    expect(fillSeries(['01.02.0010', '01.02.0020'], 2, () => null, fmt)).toEqual(['01.02.0030', '01.02.0040']);
    expect(fillSeries(['A-09'], 2, () => null, fmt)).toEqual(['A-10', 'A-11']);
  });
  it('repeats plain text', () => {
    expect(fillSeries(['Wall', 'Slab'], 3, () => null, fmt)).toEqual(['Wall', 'Slab', 'Wall']);
  });
});

describe('undo', () => {
  it('reverts a whole bulk action at once and redoes it', () => {
    const h = new SheetHistory();
    h.push([
      { rowId: 'a', field: 'unit', before: 'm', after: 'm2' },
      { rowId: 'b', field: 'unit', before: 'm', after: 'm2' },
    ]);
    expect(h.undo()).toEqual([
      { rowId: 'b', field: 'unit', before: 'm2', after: 'm' },
      { rowId: 'a', field: 'unit', before: 'm2', after: 'm' },
    ]);
    expect(h.canRedo).toBe(true);
    expect(h.redo()).toHaveLength(2);
    expect(h.undo()).not.toBeNull();
  });
  it('ignores a no-op action', () => {
    const h = new SheetHistory();
    h.push([{ rowId: 'a', field: 'unit', before: 'm', after: 'm' }]);
    expect(h.canUndo).toBe(false);
  });
});

describe('find and replace', () => {
  const texts = [
    ['Concrete wall', 'm2'],
    ['Concrete slab', 'm3'],
    ['Brick', 'm2'],
  ];
  const grid: Grid = {
    rowIds: ['a', 'b', 'c'],
    fields: ['description', 'unit'],
    text: (r, c) => texts[r]![c]!,
    editable: (r) => r !== 1,
  };
  it('finds within the scope only', () => {
    expect(findAll(grid, 'concrete', { r0: 0, r1: 2, c0: 0, c1: 1 })).toHaveLength(2);
    expect(findAll(grid, 'concrete', { r0: 1, r1: 2, c0: 0, c1: 1 })).toHaveLength(1);
  });
  it('skips read-only cells and reports them', () => {
    const { changes, skipped } = replaceAll(grid, 'Concrete', 'RC', { r0: 0, r1: 2, c0: 0, c1: 0 });
    expect(changes).toEqual([{ rowId: 'a', field: 'description', before: 'Concrete wall', after: 'RC wall' }]);
    expect(skipped).toBe(1);
  });
});

describe('cell formulas', () => {
  const vars = new Map([['GFA', { type: 'number' as const, value: 120 }]]);
  const rows = [
    pos('a', '01.010', { quantity: 4 }),
    pos('b', '01.020', { metadata: { formula: '=pos("01.010").qty * 2' }, quantity: 8 }),
  ];
  it('evaluates variables', () => {
    expect(evaluateCellFormula('=$GFA * 0.5', 'a', 'quantity', rows, vars)).toEqual({ ok: true, value: 60 });
  });
  it('refuses a loop back through a link, from a quantity or a rate cell', () => {
    for (const field of ['quantity', 'unit_rate'] as const) {
      const out = evaluateCellFormula('=pos("01.020").qty', 'a', field, rows, vars);
      expect(out).toEqual({ ok: false, error: 'cycle', cycle: expect.arrayContaining(['01.010', '01.020']) });
    }
  });
  it('shows dependencies and audits variable users', () => {
    expect(dependencyInfo('a', rows)).toEqual({ uses: [], usedBy: ['01.020'] });
    const withVar = [...rows, pos('c', '02.010', { metadata: { rate_formula: '=$GFA / 10' } })];
    expect(positionsUsingVariable('$gfa', withVar)).toEqual(['02.010']);
  });
  it('turns typed text into exact decimal strings and keeps the formula', () => {
    const { edits, errors } = toSheetEdits(
      [
        { rowId: 'a', field: 'quantity', before: '4', after: '1.234,5' },
        { rowId: 'b', field: 'unit_rate', before: '10', after: '=$GFA / 8' },
        { rowId: 'a', field: 'unit', before: 'm2', after: 'm3' },
      ],
      rows,
      vars,
      'de-DE',
    );
    expect(errors).toEqual([]);
    expect(edits).toEqual([
      { id: 'a', version: 0, fields: { quantity: '1234.5', unit: 'm3' } },
      { id: 'b', version: 0, fields: { unit_rate: '15', metadata: { rate_formula: '=$GFA / 8' } } },
    ]);
    expect(editText(rows[1]!, 'quantity', 'de-DE')).toBe('=pos("01.010").qty * 2');
  });
});

describe('paste of new rows', () => {
  it('skips a header line, reads locale numbers and flags bad rows', () => {
    const preview = buildPreview(
      [
        ['Pos', 'Text', 'Unit', 'Qty', 'Rate'],
        ['03.010', 'Screed', 'm2', '1.250,5', '18,40'],
        ['03.020', '', 'm2', 'x', ''],
      ],
      ['ordinal', 'description', 'unit', 'quantity', 'unit_rate'],
      'de-DE',
    );
    expect(preview).toHaveLength(2);
    expect(preview[0]).toEqual({
      row: { ordinal: '03.010', description: 'Screed', unit: 'm2', quantity: 1250.5, unit_rate: 18.4 },
      issues: [],
    });
    expect(preview[1]!.issues.map((i) => i.code)).toEqual(['not_a_number', 'description_missing']);
  });
});

describe('outline', () => {
  const rows = [
    pos('s', '01', { unit: '', quantity: 0, unit_rate: 0 }),
    pos('a', '01.010', { parent_id: 's' }),
    pos('t', '02', { unit: '', quantity: 0, unit_rate: 0 }),
  ];
  it('collapses a group and names levels per standard', () => {
    const o = buildOutline(rows);
    expect(o.map((r) => r.level)).toEqual([0, 1, 0]);
    expect(visibleRows(o, new Set(['s'])).map((r) => r.position.id)).toEqual(['s', 't']);
    expect(levelKey('GAEB', 0)).toBe('boq.sheet.level_gaeb_lot');
    expect(levelKey('din276', 5)).toBe('boq.sheet.level_din276_3');
    expect(ordinalHeaderKey('masterformat')).toBe('boq.sheet.col_ordinal_masterformat');
    expect(ordinalHeaderKey('other')).toBe('boq.sheet.col_ordinal');
  });
});
