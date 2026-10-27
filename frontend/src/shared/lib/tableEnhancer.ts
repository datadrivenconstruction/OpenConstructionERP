// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Spreadsheet behaviour for every plain <table> in the app, switched on from
 * Settings (`tablePrefs.ts`). The pages keep rendering ordinary tables; this
 * layer adds, on top of the DOM React produced:
 *
 *  - excel mode: header click sorts (asc, desc, off), a filter button per
 *    column, drag handles to resize, a totals row for numeric columns, range
 *    selection by dragging over cells and Ctrl+C as tab-separated text that
 *    pastes into a spreadsheet. Frozen header and first column are CSS.
 *  - keyboard mode: arrow keys move between cells, Enter opens the row.
 *
 * It only reorders and hides rows React already rendered and adds its own
 * nodes (marked data-oe-*), so React keeps ownership of the content. A table
 * opts out with data-no-enhance on itself or an ancestor.
 */
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { TABLE_PREFS_EVENT, applyTablePrefs, readTablePrefs, type TablePrefs } from './tablePrefs';

export interface EnhancerLabels {
  total: string;
  filter: string;
  filterPlaceholder: string;
  copied: (cells: number) => string;
}

let labels: EnhancerLabels = {
  total: 'Total',
  filter: 'Filter',
  filterPlaceholder: 'Contains...',
  copied: (n) => `${n} cells copied`,
};

export function setEnhancerLabels(next: EnhancerLabels): void {
  labels = next;
}

/* ── Pure helpers (unit tested) ─────────────────────────────────────────── */

/**
 * Read a displayed number in any common notation: "1,234.50", "1.234,50",
 * "1 234,5 m3", "-12 %", "(450.00)". Null for text that is not one number.
 */
export function parseDisplayedNumber(raw: string): number | null {
  let s = raw.replace(/[   ']/g, ' ').trim();
  if (!s) return null;
  let negative = false;
  if (/^\(.*\)$/.test(s)) {
    negative = true;
    s = s.slice(1, -1);
  }
  const m = /[-−]? ?\d[\d ,.]*/.exec(s);
  if (!m) return null;
  // Anything else must be a short unit or currency, never another number (m2, m3 are units).
  const rest = (s.slice(0, m.index) + s.slice(m.index + m[0].length)).trim();
  if (/\d/.test(rest.replace(/[a-z][23]\b/gi, '')) || rest.length > 6) return null;
  let num = m[0].replace(/−/, '-').replace(/ /g, '');
  const lastDot = num.lastIndexOf('.');
  const lastComma = num.lastIndexOf(',');
  if (lastDot >= 0 && lastComma >= 0) {
    const dec = lastDot > lastComma ? '.' : ',';
    const thou = dec === '.' ? ',' : '.';
    num = num.split(thou).join('').replace(dec, '.');
  } else if (lastComma >= 0) {
    const parts = num.split(',');
    const thousands = parts.length > 2 || (parts.length === 2 && parts[1]!.length === 3 && parts[0]!.length <= 3);
    num = thousands ? parts.join('') : parts.join('.');
  } else if (lastDot >= 0 && num.split('.').length > 2) {
    num = num.split('.').join('');
  }
  const v = Number(num);
  if (!Number.isFinite(v)) return null;
  return negative ? -Math.abs(v) : v;
}

/** One cell's text as a spreadsheet takes it: no tabs or line breaks inside. */
export function cellText(el: Element): string {
  const text = (el as HTMLElement).innerText ?? el.textContent ?? '';
  return text.replace(/[\t\r\n]+/g, ' ').replace(/ {2,}/g, ' ').trim();
}

/** Rows of cells to tab-separated text. */
export function toTsv(rows: string[][]): string {
  return rows.map((r) => r.join('\t')).join('\n');
}

/** Compare two cell texts: numbers by value, the rest by locale collation. */
export function compareCells(a: string, b: string, locale?: string): number {
  const na = parseDisplayedNumber(a);
  const nb = parseDisplayedNumber(b);
  if (na !== null && nb !== null) return na - nb;
  if (na !== null) return -1;
  if (nb !== null) return 1;
  return a.localeCompare(b, locale, { numeric: true, sensitivity: 'base' });
}

/** Column sums where most filled cells are numbers; null for text columns. */
export function columnTotals(rows: string[][]): (number | null)[] {
  const width = Math.max(0, ...rows.map((r) => r.length));
  const out: (number | null)[] = [];
  for (let c = 0; c < width; c++) {
    let filled = 0;
    let numeric = 0;
    let sum = 0;
    for (const r of rows) {
      const t = (r[c] ?? '').trim();
      if (!t || t === '-' || t === '—') continue;
      filled++;
      const v = parseDisplayedNumber(t);
      if (v !== null) {
        numeric++;
        sum += v;
      }
    }
    out.push(filled > 0 && numeric / filled >= 0.8 && c > 0 ? sum : null);
  }
  return out;
}

/* ── DOM layer ──────────────────────────────────────────────────────────── */

interface TableState {
  sortCol: number;
  sortDir: 1 | -1;
  filters: Map<number, string>;
  hidden: Set<number>;
}

/** What a saved list view stores; keys are column header texts. */
export interface TableViewState {
  filters: Record<string, string>;
  /** Visible columns in order; empty when every column shows. */
  columns: string[];
  widths: Record<string, number>;
  sort: { key: string; dir: 'asc' | 'desc' } | null;
}

const states = new WeakMap<HTMLTableElement, TableState>();
let prefs: TablePrefs = { excel: false, keyboard: false };
let observer: MutationObserver | null = null;
let pending = false;
let selection: { table: HTMLTableElement; r0: number; c0: number; r1: number; c1: number } | null = null;
let dragging = false;

function eligible(table: HTMLTableElement): boolean {
  if (table.closest('[data-no-enhance], [contenteditable="true"], .ag-root-wrapper')) return false;
  return !!table.tHead && table.tBodies.length > 0;
}

function bodyRows(table: HTMLTableElement): HTMLTableRowElement[] {
  return Array.from(table.tBodies).flatMap((b) =>
    Array.from(b.rows).filter((r) => !r.hasAttribute('data-oe-total')),
  );
}

function headerCells(table: HTMLTableElement): HTMLTableCellElement[] {
  const head = table.tHead;
  const row = head?.rows[head.rows.length - 1];
  return row ? Array.from(row.cells) : [];
}

function rowTexts(rows: HTMLTableRowElement[]): string[][] {
  return rows.map((r) => Array.from(r.cells).map(cellText));
}

function stateOf(table: HTMLTableElement): TableState {
  let s = states.get(table);
  if (!s) {
    s = { sortCol: -1, sortDir: 1, filters: new Map(), hidden: new Set() };
    states.set(table, s);
  }
  return s;
}

function applySort(table: HTMLTableElement): void {
  const s = stateOf(table);
  headerCells(table).forEach((th, i) => {
    if (i === s.sortCol) th.setAttribute('aria-sort', s.sortDir === 1 ? 'ascending' : 'descending');
    else if (th.dataset.oeSortable) th.removeAttribute('aria-sort');
  });
  if (s.sortCol < 0) return;
  const locale = getNumberLocale();
  for (const body of Array.from(table.tBodies)) {
    const rows = Array.from(body.rows).filter((r) => !r.hasAttribute('data-oe-total'));
    // Rows with a spanning cell (group headers, details) keep the table's own order.
    if (rows.some((r) => Array.from(r.cells).some((c) => c.colSpan > 1))) continue;
    const sorted = [...rows].sort(
      (a, b) =>
        s.sortDir *
        compareCells(cellText(a.cells[s.sortCol] ?? a), cellText(b.cells[s.sortCol] ?? b), locale),
    );
    if (sorted.every((r, i) => r === rows[i])) continue;
    for (const r of sorted) body.appendChild(r);
  }
}

function applyFilters(table: HTMLTableElement): void {
  const { filters } = stateOf(table);
  for (const r of bodyRows(table)) {
    let show = true;
    for (const [col, needle] of filters) {
      const cell = r.cells[col];
      if (cell && !cellText(cell).toLowerCase().includes(needle.toLowerCase())) show = false;
    }
    if (show) r.removeAttribute('data-oe-hidden');
    else r.setAttribute('data-oe-hidden', '');
  }
  headerCells(table).forEach((th, i) => {
    const btn = th.querySelector<HTMLElement>('[data-oe-filter-btn]');
    if (btn) btn.dataset.active = filters.has(i) ? 'true' : 'false';
  });
}

function applyTotals(table: HTMLTableElement): void {
  const visible = bodyRows(table).filter((r) => !r.hasAttribute('data-oe-hidden'));
  const existing = table.querySelector('tfoot[data-oe-total]');
  if (table.tFoot && !existing) return; // the page has its own footer
  const totals = columnTotals(rowTexts(visible));
  if (visible.length < 2 || totals.every((t) => t === null)) {
    existing?.remove();
    return;
  }
  const foot = (existing as HTMLTableSectionElement | null) ?? document.createElement('tfoot');
  foot.setAttribute('data-oe-total', '');
  const fmt = new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 2 });
  const width = headerCells(table).length || totals.length;
  const cells: string[] = [];
  for (let c = 0; c < width; c++) {
    const t = totals[c];
    cells.push(c === 0 ? labels.total : t === null || t === undefined ? '' : fmt.format(t));
  }
  const html = cells
    .map((v, c) => `<td${c > 0 && v ? ' data-numeric' : ''}>${v.replace(/</g, '&lt;')}</td>`)
    .join('');
  if (foot.dataset.html !== html) {
    foot.innerHTML = `<tr data-oe-total>${html}</tr>`;
    foot.dataset.html = html;
  }
  if (!existing) table.appendChild(foot);
}

function openFilter(table: HTMLTableElement, col: number, anchor: HTMLElement): void {
  document.querySelector('[data-oe-filter-pop]')?.remove();
  const s = stateOf(table);
  const pop = document.createElement('div');
  pop.setAttribute('data-oe-filter-pop', '');
  const input = document.createElement('input');
  input.type = 'search';
  input.placeholder = labels.filterPlaceholder;
  input.setAttribute('aria-label', labels.filter);
  input.value = s.filters.get(col) ?? '';
  pop.appendChild(input);
  const r = anchor.getBoundingClientRect();
  pop.style.top = `${r.bottom + 4}px`;
  pop.style.left = `${Math.max(8, r.left - 120)}px`;
  document.body.appendChild(pop);
  input.focus();
  input.addEventListener('input', () => {
    const v = input.value.trim();
    if (v) s.filters.set(col, v);
    else s.filters.delete(col);
    applyFilters(table);
    applyTotals(table);
  });
  const close = (e: Event) => {
    if (e instanceof KeyboardEvent && e.key !== 'Escape' && e.key !== 'Enter') return;
    if (e instanceof MouseEvent && pop.contains(e.target as Node)) return;
    pop.remove();
    document.removeEventListener('mousedown', close, true);
    document.removeEventListener('keydown', close, true);
  };
  setTimeout(() => {
    document.addEventListener('mousedown', close, true);
    document.addEventListener('keydown', close, true);
  });
}

function decorateHeader(table: HTMLTableElement): void {
  headerCells(table).forEach((th, col) => {
    if (th.dataset.oeSortable || th.colSpan > 1) return;
    th.dataset.oeSortable = 'true';
    const filterBtn = document.createElement('button');
    filterBtn.type = 'button';
    filterBtn.setAttribute('data-oe-filter-btn', '');
    filterBtn.setAttribute('aria-label', labels.filter);
    filterBtn.title = labels.filter;
    filterBtn.textContent = '▾';
    filterBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openFilter(table, col, filterBtn);
    });
    const handle = document.createElement('span');
    handle.setAttribute('data-oe-resize', '');
    handle.setAttribute('aria-hidden', 'true');
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const startX = e.clientX;
      const startW = th.getBoundingClientRect().width;
      const move = (ev: MouseEvent) => {
        const w = Math.max(48, startW + (ev.clientX - startX) * (document.dir === 'rtl' ? -1 : 1));
        th.style.width = th.style.minWidth = `${w}px`;
      };
      const up = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
    handle.addEventListener('click', (e) => e.stopPropagation());
    th.append(filterBtn, handle);
    th.addEventListener('click', (e) => {
      if (!prefs.excel) return;
      if ((e.target as HTMLElement).closest('button:not([data-oe-filter-btn]), a, input, select, label')) return;
      const s = stateOf(table);
      if (s.sortCol !== col) {
        s.sortCol = col;
        s.sortDir = 1;
      } else if (s.sortDir === 1) s.sortDir = -1;
      else s.sortCol = -1;
      applySort(table);
    });
  });
}

function applyHidden(table: HTMLTableElement): void {
  const { hidden } = stateOf(table);
  const rows = [...Array.from(table.tHead?.rows ?? []), ...bodyRows(table), ...Array.from(table.tFoot?.rows ?? [])];
  for (const r of rows) {
    Array.from(r.cells).forEach((c, i) => {
      if (hidden.has(i)) c.setAttribute('data-oe-col-hidden', '');
      else c.removeAttribute('data-oe-col-hidden');
    });
  }
}

/** Header texts of a table, the keys a saved view uses. */
export function columnKeys(table: HTMLTableElement): string[] {
  return headerCells(table).map((th, i) => {
    const clone = th.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('[data-oe-filter-btn], [data-oe-resize]').forEach((n) => n.remove());
    return (clone.textContent ?? '').replace(/\s+/g, ' ').trim() || `#${i + 1}`;
  });
}

/** The enhanced table a page is about: the one with the most rows. */
export function primaryTable(root: ParentNode = document): HTMLTableElement | null {
  let best: HTMLTableElement | null = null;
  let most = 0;
  root.querySelectorAll<HTMLTableElement>('table[data-oe-enhanced]').forEach((t) => {
    const n = bodyRows(t).length;
    if (n > most && t.offsetParent !== null) {
      best = t;
      most = n;
    }
  });
  return best;
}

export function readTableState(table: HTMLTableElement): TableViewState {
  const s = stateOf(table);
  const keys = columnKeys(table);
  const widths: Record<string, number> = {};
  headerCells(table).forEach((th, i) => {
    const w = parseInt(th.style.width, 10);
    const k = keys[i];
    if (w > 0 && k) widths[k] = w;
  });
  const filters: Record<string, string> = {};
  for (const [col, text] of s.filters) {
    const k = keys[col];
    if (k) filters[k] = text;
  }
  return {
    filters,
    columns: s.hidden.size ? keys.filter((_, i) => !s.hidden.has(i)) : [],
    widths,
    sort: s.sortCol >= 0 && keys[s.sortCol] ? { key: keys[s.sortCol]!, dir: s.sortDir === 1 ? 'asc' : 'desc' } : null,
  };
}

export function applyTableState(table: HTMLTableElement, view: Partial<TableViewState>): void {
  const s = stateOf(table);
  const keys = columnKeys(table);
  const index = (key: string) => keys.indexOf(key);
  s.filters = new Map();
  for (const [key, text] of Object.entries(view.filters ?? {})) if (index(key) >= 0 && text) s.filters.set(index(key), text);
  s.hidden = new Set(view.columns?.length ? keys.map((_, i) => i).filter((i) => !view.columns!.includes(keys[i] ?? '')) : []);
  s.sortCol = view.sort ? index(view.sort.key) : -1;
  s.sortDir = view.sort?.dir === 'desc' ? -1 : 1;
  headerCells(table).forEach((th, i) => {
    const k = keys[i];
    const w = k ? view.widths?.[k] : undefined;
    th.style.width = th.style.minWidth = w ? `${w}px` : '';
  });
  applyHidden(table);
  applyFilters(table);
  applySort(table);
  applyTotals(table);
}

/** Show or hide one column by index. */
export function setColumnHidden(table: HTMLTableElement, col: number, hide: boolean): void {
  const s = stateOf(table);
  if (hide) s.hidden.add(col);
  else s.hidden.delete(col);
  applyHidden(table);
}

export function hiddenColumns(table: HTMLTableElement): number[] {
  return [...stateOf(table).hidden];
}

function markNumeric(table: HTMLTableElement): void {
  const rows = bodyRows(table).slice(0, 50);
  const totals = columnTotals(rowTexts(rows));
  totals.forEach((t, c) => {
    if (t === null) return;
    for (const r of rows) r.cells[c]?.setAttribute('data-numeric', '');
    headerCells(table)[c]?.setAttribute('data-numeric', '');
  });
}

function enhance(table: HTMLTableElement): void {
  if (!eligible(table)) return;
  table.dataset.oeEnhanced = 'true';
  markNumeric(table);
  if (stateOf(table).hidden.size) applyHidden(table);
  if (prefs.excel) {
    decorateHeader(table);
    applyFilters(table);
    applySort(table);
    applyTotals(table);
  }
  if (prefs.keyboard) {
    for (const r of bodyRows(table)) for (const c of Array.from(r.cells)) if (!c.hasAttribute('tabindex')) c.tabIndex = -1;
    const first = bodyRows(table)[0]?.cells[0];
    if (first && !table.querySelector('td[tabindex="0"]')) first.tabIndex = 0;
  }
}

function scan(): void {
  pending = false;
  observer?.disconnect();
  try {
    document.querySelectorAll<HTMLTableElement>('table').forEach(enhance);
  } finally {
    observer?.observe(document.body, { childList: true, subtree: true });
  }
}

function schedule(): void {
  if (pending) return;
  pending = true;
  requestAnimationFrame(scan);
}

/* ── Range selection and copy ───────────────────────────────────────────── */

function cellPos(td: HTMLTableCellElement): { r: number; c: number } | null {
  const row = td.parentElement as HTMLTableRowElement | null;
  const table = td.closest('table');
  if (!row || !table) return null;
  return { r: bodyRows(table).indexOf(row), c: td.cellIndex };
}

function paintSelection(): void {
  document.querySelectorAll('[data-oe-sel]').forEach((el) => el.removeAttribute('data-oe-sel'));
  if (!selection) return;
  const { table, r0, c0, r1, c1 } = selection;
  const rows = bodyRows(table);
  for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
    for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) rows[r]?.cells[c]?.setAttribute('data-oe-sel', '');
  }
}

function selectedTsv(): { tsv: string; count: number } | null {
  if (!selection) return null;
  const { table, r0, c0, r1, c1 } = selection;
  const rows = bodyRows(table);
  const out: string[][] = [];
  const cols: [number, number] = [Math.min(c0, c1), Math.max(c0, c1)];
  const header = headerCells(table).slice(cols[0], cols[1] + 1).map(cellText);
  const whole = Math.min(r0, r1) === 0 && Math.max(r0, r1) === rows.length - 1;
  if (whole && header.length) out.push(header);
  for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
    if (rows[r]?.hasAttribute('data-oe-hidden')) continue;
    const line: string[] = [];
    for (let c = cols[0]; c <= cols[1]; c++) {
      const cell = rows[r]?.cells[c];
      line.push(cell ? cellText(cell) : '');
    }
    out.push(line);
  }
  return { tsv: toTsv(out), count: out.length * (cols[1] - cols[0] + 1) };
}

function onMouseDown(e: MouseEvent): void {
  if (!prefs.excel || e.button !== 0) return;
  const td = (e.target as HTMLElement).closest?.('td') as HTMLTableCellElement | null;
  const table = td?.closest('table') as HTMLTableElement | null;
  if (!td || !table || table.dataset.oeEnhanced !== 'true' || td.closest('tfoot')) {
    if (selection && !(e.target as HTMLElement).closest?.('[data-oe-filter-pop]')) {
      selection = null;
      paintSelection();
    }
    return;
  }
  if ((e.target as HTMLElement).closest('a, button, input, select, textarea, [role="button"]')) return;
  const p = cellPos(td);
  if (!p || p.r < 0) return;
  if (e.shiftKey && selection?.table === table) {
    selection = { ...selection, r1: p.r, c1: p.c };
  } else {
    selection = { table, r0: p.r, c0: p.c, r1: p.r, c1: p.c };
  }
  dragging = true;
  paintSelection();
}

function onMouseOver(e: MouseEvent): void {
  if (!dragging || !selection) return;
  const td = (e.target as HTMLElement).closest?.('td') as HTMLTableCellElement | null;
  if (!td || td.closest('table') !== selection.table) return;
  const p = cellPos(td);
  if (!p || p.r < 0) return;
  if (p.r !== selection.r1 || p.c !== selection.c1) {
    selection = { ...selection, r1: p.r, c1: p.c };
    window.getSelection()?.removeAllRanges();
    paintSelection();
  }
}

function onCopy(e: ClipboardEvent): void {
  if (!prefs.excel || !selection) return;
  const single = selection.r0 === selection.r1 && selection.c0 === selection.c1;
  // A single cell with a text selection inside copies the text as usual.
  if (single && window.getSelection()?.toString()) return;
  const out = selectedTsv();
  if (!out || !e.clipboardData) return;
  e.clipboardData.setData('text/plain', out.tsv);
  e.preventDefault();
  window.dispatchEvent(new CustomEvent('oe:table-copied', { detail: labels.copied(out.count) }));
}

/* ── Keyboard navigation ────────────────────────────────────────────────── */

function onKeyDown(e: KeyboardEvent): void {
  if (!prefs.keyboard) return;
  const td = (e.target as HTMLElement).closest?.('td') as HTMLTableCellElement | null;
  if (!td || e.target !== td) return;
  const table = td.closest('table') as HTMLTableElement | null;
  if (!table || table.dataset.oeEnhanced !== 'true') return;
  const rows = bodyRows(table).filter((r) => !r.hasAttribute('data-oe-hidden'));
  const row = td.parentElement as HTMLTableRowElement;
  let r = rows.indexOf(row);
  let c = td.cellIndex;
  const rtl = document.dir === 'rtl';
  switch (e.key) {
    case 'ArrowDown': r = Math.min(rows.length - 1, r + 1); break;
    case 'ArrowUp': r = Math.max(0, r - 1); break;
    case 'ArrowRight': c += rtl ? -1 : 1; break;
    case 'ArrowLeft': c += rtl ? 1 : -1; break;
    case 'Home': c = 0; break;
    case 'End': c = row.cells.length - 1; break;
    case 'Enter': {
      const target =
        row.querySelector<HTMLElement>('a[href], button:not([disabled])') ?? (row.onclick || row.getAttribute('role') === 'button' ? row : null);
      if (target) {
        e.preventDefault();
        target.click();
      }
      return;
    }
    default:
      return;
  }
  const next = rows[r]?.cells[Math.max(0, Math.min(c, (rows[r]?.cells.length ?? 1) - 1))];
  if (!next) return;
  e.preventDefault();
  td.tabIndex = -1;
  next.tabIndex = 0;
  next.focus();
}

/* ── Lifecycle ──────────────────────────────────────────────────────────── */

function onPrefs(): void {
  prefs = readTablePrefs();
  applyTablePrefs(prefs);
  if (!prefs.excel) {
    document.querySelectorAll('[data-oe-filter-btn], [data-oe-resize], tfoot[data-oe-total]').forEach((n) => n.remove());
    document.querySelectorAll('[data-oe-hidden]').forEach((n) => n.removeAttribute('data-oe-hidden'));
    document.querySelectorAll<HTMLElement>('[data-oe-sortable]').forEach((n) => {
      delete n.dataset.oeSortable;
      n.removeAttribute('aria-sort');
    });
    selection = null;
    paintSelection();
  }
  schedule();
}

/** Start once at app boot; returns a stop function. */
export function startTableEnhancer(): () => void {
  if (typeof window === 'undefined' || observer) return () => {};
  prefs = readTablePrefs();
  applyTablePrefs(prefs);
  observer = new MutationObserver(schedule);
  observer.observe(document.body, { childList: true, subtree: true });
  const up = () => {
    dragging = false;
  };
  document.addEventListener('mousedown', onMouseDown, true);
  document.addEventListener('mouseover', onMouseOver);
  document.addEventListener('mouseup', up);
  document.addEventListener('copy', onCopy);
  document.addEventListener('keydown', onKeyDown);
  window.addEventListener(TABLE_PREFS_EVENT, onPrefs);
  schedule();
  return () => {
    observer?.disconnect();
    observer = null;
    document.removeEventListener('mousedown', onMouseDown, true);
    document.removeEventListener('mouseover', onMouseOver);
    document.removeEventListener('mouseup', up);
    document.removeEventListener('copy', onCopy);
    document.removeEventListener('keydown', onKeyDown);
    window.removeEventListener(TABLE_PREFS_EVENT, onPrefs);
  };
}
