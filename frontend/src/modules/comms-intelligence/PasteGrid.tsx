// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The pasted-Excel grid.
 *
 * What this replaces was a bare `<textarea>` with a placeholder saying
 * "paste straight from Excel". The backend does honour tab-separated
 * lines and renders them as a real table in the email — but only if the
 * paste survived untouched AND had two or more rows, and nothing on the
 * screen showed you whether it had. A one-row paste silently went out as
 * a paragraph, and a ragged row (Excel drops trailing empty cells) came
 * out misaligned against its heading.
 *
 * So: intercept the paste, parse it properly, and show it as the grid it
 * is. The value handed back is still tab-separated text — the wire
 * format the email builder already reads — so nothing downstream changes
 * and an item raised before this existed still opens.
 *
 * Two parsers, because a clipboard from Excel carries both:
 *   text/html   — a real <table>; cells can contain commas and quotes
 *                 safely, so this is tried FIRST.
 *   text/plain  — tab-separated, the fallback Excel also writes.
 *
 * The first row is the heading row. It is not a guess: it is what the
 * email renders bold at the top of the table, so it has to be visible
 * and editable here rather than inferred later.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Table2, Trash2 } from 'lucide-react';
import { ContextMenu } from './ContextMenu';

/** Excel drops trailing empty cells, so rows arrive ragged. Square them off. */
function pad(rows: string[][]): string[][] {
  const width = rows.reduce((w, r) => Math.max(w, r.length), 0);
  return rows.map((r) => [...r, ...Array(Math.max(0, width - r.length)).fill('')]);
}

/** A real <table> off the clipboard. Returns [] when there isn't one. */
export function parseHtmlTable(html: string): string[][] {
  if (!html || !/<t[dhr]\b|<table\b/i.test(html)) return [];
  // DOMParser, not innerHTML on a live node: this is clipboard content
  // from who-knows-where and it must never execute or load anything.
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const table = doc.querySelector('table');
  if (!table) return [];
  const rows = [...table.querySelectorAll('tr')]
    .map((tr) =>
      [...tr.querySelectorAll('th,td')].map((c) => (c.textContent ?? '').replace(/\s+/g, ' ').trim()),
    )
    .filter((r) => r.some((c) => c !== ''));
  return pad(rows);
}

/** Tab-separated (Excel's plain-text flavour). Commas are NOT separators
 *  here — "Cable, 4 core" is one cell and splitting it would be wrong. */
export function parseDelimited(text: string): string[][] {
  const lines = text.split(/\r\n|\r|\n/).filter((l) => l.trim() !== '');
  if (!lines.length) return [];
  const rows = lines.map((l) => l.split('\t'));
  return pad(rows);
}

export function toTsv(rows: string[][]): string {
  return rows
    .filter((r) => r.some((c) => c.trim() !== ''))
    .map((r) => r.map((c) => c.replace(/\t/g, ' ').trim()).join('\t'))
    .join('\n');
}

export function fromTsv(value: string): string[][] {
  const rows = parseDelimited(value ?? '');
  return rows.length ? rows : [];
}

export function PasteGrid({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<string[][]>(() => fromTsv(value));
  const cellRefs = useRef<Record<string, HTMLInputElement | null>>({});
  // Which column the cursor is in. On a table wide enough to scroll,
  // "which column am I typing into" is genuinely hard to answer without
  // the whole column lighting up.
  const [hotCol, setHotCol] = useState<number | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; r: number; c: number } | null>(null);
  // What we last handed upward. Without it, our own onChange comes back
  // as a "new" value and re-parses the grid mid-edit, which moves the
  // caret to the end of whatever cell you are typing in.
  const ours = useRef<string>(value);

  useEffect(() => {
    if (value !== ours.current) {
      setRows(fromTsv(value));
      ours.current = value;
    }
  }, [value]);

  const push = (next: string[][]) => {
    setRows(next);
    const tsv = toTsv(next);
    ours.current = tsv;
    onChange(tsv);
  };

  const width = useMemo(() => rows.reduce((w, r) => Math.max(w, r.length), 0), [rows]);

  const setCell = (r: number, c: number, v: string) => {
    const next = rows.map((row) => [...row]);
    next[r]![c] = v;
    push(next);
  };

  const addRow = () => push([...rows, Array(Math.max(1, width)).fill('')]);
  const addColumn = () => push(rows.map((r) => [...r, '']));
  const deleteRow = (r: number) => push(rows.filter((_, i) => i !== r));
  const deleteColumn = (c: number) => push(rows.map((r) => r.filter((_, i) => i !== c)));
  const insertRowAt = (r: number) =>
    push([...rows.slice(0, r), Array(Math.max(1, width)).fill(''), ...rows.slice(r)]);
  const duplicateRow = (r: number) =>
    push([...rows.slice(0, r + 1), [...(rows[r] ?? [])], ...rows.slice(r + 1)]);
  const insertColumnAt = (c: number) =>
    push(rows.map((r) => [...r.slice(0, c), '', ...r.slice(c)]));
  const moveRow = (r: number, by: number) => {
    // Row 0 is the heading row and does not move: the email renders it
    // bold at the top, so sliding a data row above it would silently
    // retitle the table.
    const to = r + by;
    if (r === 0 || to <= 0 || to >= rows.length) return;
    const next = [...rows];
    const [taken] = next.splice(r, 1);
    next.splice(to, 0, taken!);
    push(next);
  };

  const onPaste = (e: React.ClipboardEvent, atRow: number, atCol: number) => {
    const html = e.clipboardData.getData('text/html');
    const text = e.clipboardData.getData('text/plain');
    const parsed = parseHtmlTable(html);
    const grid = parsed.length ? parsed : parseDelimited(text);
    // A single cell of plain text is an ordinary paste into that cell -
    // hijacking it would make typing in the grid feel broken.
    if (grid.length <= 1 && (grid[0]?.length ?? 0) <= 1) return;
    e.preventDefault();
    // Pasting into the empty grid REPLACES it; pasting into a populated
    // one lands where the cursor is, so a second table can be appended
    // without retyping the first.
    if (!rows.length || (rows.length === 1 && rows[0]!.every((c) => c === ''))) {
      push(pad(grid));
      return;
    }
    const next = rows.map((row) => [...row]);
    grid.forEach((gRow, gi) => {
      const r = atRow + gi;
      if (!next[r]) next[r] = Array(width).fill('');
      gRow.forEach((cell, gj) => {
        next[r]![atCol + gj] = cell;
      });
    });
    push(pad(next));
  };

  const focusCell = (r: number, c: number) => {
    cellRefs.current[`${r}:${c}`]?.focus();
    cellRefs.current[`${r}:${c}`]?.select();
  };

  const onKeyDown = (e: React.KeyboardEvent, r: number, c: number) => {
    // Tab is left alone: it is the browser's own next-field move and
    // overriding it breaks getting OUT of the grid with the keyboard.
    if (e.key === 'ArrowDown' || (e.key === 'Enter' && !e.shiftKey)) {
      e.preventDefault();
      if (r + 1 >= rows.length) addRow();
      setTimeout(() => focusCell(r + 1, c), 0);
    } else if (e.key === 'ArrowUp' && r > 0) {
      e.preventDefault();
      focusCell(r - 1, c);
    }
  };

  if (!rows.length) {
    // Nothing pasted yet: one honest box that says what it wants. The
    // paste handler is on it, so the first paste builds the grid.
    return (
      <textarea
        className="qpaste"
        value=""
        placeholder={
          placeholder ??
          t('ci.paste_hint', { defaultValue: 'Paste straight from Excel — the cells become a table in the email' })
        }
        onChange={(e) => push(parseDelimited(e.target.value))}
        onPaste={(e) => {
          const grid = parseHtmlTable(e.clipboardData.getData('text/html'));
          const rowsIn = grid.length ? grid : parseDelimited(e.clipboardData.getData('text/plain'));
          if (!rowsIn.length) return;
          e.preventDefault();
          push(pad(rowsIn));
        }}
      />
    );
  }

  return (
    <div className="qxlwrap">
      <div className="row" style={{ gap: 6, marginBottom: 4 }}>
        <span className="badge">
          <Table2 className="h-3 w-3" />{' '}
          {t('ci.grid_size', {
            defaultValue: '{{r}} rows × {{c}} columns',
            r: Math.max(0, rows.length - 1),
            c: width,
          })}
        </span>
        <span className="v">
          {t('ci.grid_head_note', { defaultValue: 'the first row is the heading row in the email' })}
        </span>
        <button type="button" className="b mini" onClick={addRow}>
          <Plus className="h-3 w-3" /> {t('ci.grid_add_row', { defaultValue: 'row' })}
        </button>
        <button type="button" className="b mini" onClick={addColumn}>
          <Plus className="h-3 w-3" /> {t('ci.grid_add_col', { defaultValue: 'column' })}
        </button>
        <button type="button" className="b mini" onClick={() => push([])}>
          {t('ci.grid_clear', { defaultValue: 'clear' })}
        </button>
      </div>

      <div className="qxlscroll">
        <table className="qxl">
          <tbody>
            {/* The column strip: A, B, C… Click one to insert a column
                before it, right-click for the rest. It is also the only
                way to see which column is which once the table is wide
                enough to scroll. */}
            <tr className="cols">
              <td className="qxlno" />
              {Array.from({ length: width }).map((_, c) => (
                <td
                  key={c}
                  className={hotCol === c ? 'qxlhot' : undefined}
                  title={t('ci.grid_col_hint', {
                    defaultValue: 'Click to insert a column here · right-click for more',
                  })}
                  onClick={() => insertColumnAt(c)}
                  onContextMenu={(ev) => {
                    ev.preventDefault();
                    setMenu({ x: ev.clientX, y: ev.clientY, r: -1, c });
                  }}
                >
                  {String.fromCharCode(65 + (c % 26))}
                </td>
              ))}
              <td className="qxlno" />
            </tr>
            {rows.map((row, r) => (
              <tr key={r} className={r === 0 ? 'head' : undefined}>
                <td className="qxlno">{r === 0 ? '' : r}</td>
                {Array.from({ length: width }).map((_, c) => (
                  <td
                    key={c}
                    className={hotCol === c ? 'qxlhot' : undefined}
                    onContextMenu={(ev) => {
                      ev.preventDefault();
                      setMenu({ x: ev.clientX, y: ev.clientY, r, c });
                    }}
                  >
                    <input
                      ref={(el) => {
                        cellRefs.current[`${r}:${c}`] = el;
                      }}
                      value={row[c] ?? ''}
                      placeholder={
                        r === 0
                          ? t('ci.grid_head_ph', { defaultValue: 'heading' })
                          : t('ci.grid_cell_ph', { defaultValue: '—' })
                      }
                      onFocus={() => setHotCol(c)}
                      onMouseEnter={() => setHotCol(c)}
                      onChange={(e) => setCell(r, c, e.target.value)}
                      onPaste={(e) => onPaste(e, r, c)}
                      onKeyDown={(e) => onKeyDown(e, r, c)}
                      aria-label={
                        r === 0
                          ? t('ci.grid_head_cell', { defaultValue: 'Heading for column {{n}}', n: c + 1 })
                          : t('ci.grid_cell', { defaultValue: 'Row {{r}}, column {{c}}', r, c: c + 1 })
                      }
                    />
                  </td>
                ))}
                <td className="qxlno">
                  <button
                    type="button"
                    className="b mini"
                    onClick={() => (r === 0 ? deleteColumn(width - 1) : deleteRow(r))}
                    aria-label={
                      r === 0
                        ? t('ci.grid_del_col', { defaultValue: 'Delete the last column' })
                        : t('ci.grid_del_row', { defaultValue: 'Delete row {{n}}', n: r })
                    }
                    title={
                      r === 0
                        ? t('ci.grid_del_col', { defaultValue: 'Delete the last column' })
                        : t('ci.grid_del_row', { defaultValue: 'Delete row {{n}}', n: r })
                    }
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          items={[
            menu.r >= 0
              ? {
                  label: t('ci.grid_insert_row', { defaultValue: 'Insert a row above' }),
                  onClick: () => insertRowAt(menu.r),
                }
              : null,
            menu.r >= 0
              ? {
                  label: t('ci.grid_dupe_row', { defaultValue: 'Duplicate this row' }),
                  onClick: () => duplicateRow(menu.r),
                }
              : null,
            menu.r > 0
              ? { label: t('ci.grid_move_up', { defaultValue: 'Move up' }), onClick: () => moveRow(menu.r, -1) }
              : null,
            menu.r > 0
              ? { label: t('ci.grid_move_down', { defaultValue: 'Move down' }), onClick: () => moveRow(menu.r, 1) }
              : null,
            menu.r > 0
              ? {
                  label: t('ci.grid_del_this_row', { defaultValue: 'Delete this row' }),
                  danger: true,
                  onClick: () => deleteRow(menu.r),
                }
              : null,
            menu.r >= 0 ? null : null,
            {
              label: t('ci.grid_insert_col', {
                defaultValue: 'Insert a column before {{n}}',
                n: String.fromCharCode(65 + (menu.c % 26)),
              }),
              onClick: () => insertColumnAt(menu.c),
            },
            width > 1
              ? {
                  label: t('ci.grid_del_this_col', {
                    defaultValue: 'Delete column {{n}}',
                    n: String.fromCharCode(65 + (menu.c % 26)),
                  }),
                  danger: true,
                  onClick: () => deleteColumn(menu.c),
                }
              : null,
          ]}
        />
      )}
    </div>
  );
}
