import type { ColDef, ValueFormatterParams, ValueGetterParams, ValueSetterParams } from 'ag-grid-community';
import { convertToBase, fmtWithCurrency, resourceAwareTotalInBase } from '../boqHelpers';
import { unitColumnValueSetter } from './cellEditors';
import {
  buildFormulaContext,
  evaluateFormulaStrict,
  isFormula,
  type FormulaContext,
  type FormulaVariable,
} from './formula';
import type { Position } from '../api';

export interface BOQColumnContext {
  currencySymbol: string;
  currencyCode: string;
  locale: string;
  fmt: Intl.NumberFormat;
  t: (key: string, opts?: Record<string, string>) => string;
  /**
   * Project-level FX rates. Read off the AG Grid ``params.context``
   * (the same `gridContext` BOQGrid builds). Used by the total column's
   * `valueGetter` to rebase positions priced in a foreign currency into
   * the project base before the row is summed (Issue #111).
   *
   * Semantics: ``rate`` is "1 unit of `currency` = `rate` units of base".
   */
  fxRates?: Array<{ currency: string; rate: number; label?: string }>;
  /**
   * ── Display-currency override (Issue #88).
   * When set, every monetary cell rendered through `totalFormatter` is
   * shown converted into this currency. The conversion is view-only —
   * the database keeps base-currency values unchanged. `unit_rate` is
   * deliberately NOT re-formatted here because each position can have
   * its own source currency (v2.6.1) and rewriting it would break that
   * model. Only aggregated totals and subtotals fold through the rate.
   *
   * Shape:
   * - `code` — currency code shown after the value, e.g. "USD"
   * - `rate` — units of `code` per one base unit. To convert from base
   *   to display we DIVIDE by `rate` (FX rates store rate-to-base).
   *
   * `null` / undefined ⇒ stick with the project base currency.
   */
  displayCurrency?: { code: string; rate: number } | null;
}

// Note: `currencyFormatter` was previously applied to the unit_rate column
// but has been superseded by `UnitRateCellRenderer` (which handles both
// formatting and the inline CWICR variant pill).  Keep this comment as a
// breadcrumb so a future refactor doesn't reintroduce a duplicate
// formatter-vs-renderer race.

function totalFormatter(params: ValueFormatterParams): string {
  const ctx = params.context as BOQColumnContext | undefined;
  if (params.value == null) return '';
  const locale = ctx?.locale ?? 'de-DE';
  // Apply display-currency conversion when set. Footer rows, section
  // subtotals and per-position totals all flow through this single
  // formatter, so flipping the display currency reformats the entire
  // BOQ in one place — no per-cell branching needed downstream.
  const dc = ctx?.displayCurrency;
  if (dc && dc.rate > 0) {
    return fmtWithCurrency(params.value / dc.rate, locale, dc.code);
  }
  const currencyCode = ctx?.currencyCode ?? 'EUR';
  return fmtWithCurrency(params.value, locale, currencyCode);
}

export function getColumnDefs(context: BOQColumnContext): ColDef[] {
  const { t } = context;

  return [
    {
      headerName: '',
      colId: '_drag',
      width: 30,
      maxWidth: 30,
      minWidth: 30,
      suppressHeaderMenuButton: true,
      editable: false,
      sortable: false,
      filter: false,
      resizable: false,
      suppressMovable: true,
      rowDrag: (params) => !params.data?._isFooter,
      rowDragText: (params) => {
        if (params.rowNode?.data?._isSection) {
          return params.rowNode.data.description ?? '';
        }
        return params.rowNode?.data?.ordinal
          ? `${params.rowNode.data.ordinal} - ${params.rowNode.data.description ?? ''}`
          : params.defaultTextValue ?? '';
      },
      cellClass: 'oe-drag-handle-cell',
      cellRenderer: (params: { data?: { _isFooter?: boolean } }) => {
        if (params.data?._isFooter) return null;
        return null; // AG Grid renders the drag handle icon automatically
      },
    },
    {
      headerName: '',
      colId: '_checkbox',
      width: 24,
      maxWidth: 24,
      minWidth: 24,
      suppressHeaderMenuButton: true,
      editable: false,
      sortable: false,
      filter: false,
      resizable: false,
      suppressMovable: true,
      // checkboxSelection moved to rowSelection.checkboxes in GridOptions (AG Grid v32.2+)
      cellClass: 'flex items-center justify-center',
    },
    {
      headerName: '',
      colId: '_expand',
      field: '_expand',
      width: 32,
      minWidth: 32,
      maxWidth: 32,
      editable: false,
      sortable: false,
      filter: false,
      resizable: false,
      suppressNavigable: true,
      suppressHeaderMenuButton: true,
      cellRenderer: 'expandCellRenderer',
      cellClass: 'oe-icon-cell',
    },
    {
      headerName: t('boq.ordinal', { defaultValue: 'Pos.' }),
      field: 'ordinal',
      width: 88,
      minWidth: 70,
      editable: (params) => {
        if (params.data?._isSection || params.data?._isFooter) return false;
        return true;
      },
      cellClass: (params) => {
        const base = 'font-mono text-xs text-right !pr-2';
        const ctx = params.context as { expandedPositions?: Set<string> } | undefined;
        const isExpanded = !!params.data?.id && (ctx?.expandedPositions?.has(params.data.id) ?? false);
        return isExpanded ? `${base} font-bold` : base;
      },
      headerClass: 'ag-right-aligned-header',
    },
    {
      headerName: '',
      colId: '_bim_link',
      field: '_bim_link',
      width: 90,
      minWidth: 28,
      maxWidth: 120,
      editable: false,
      sortable: false,
      filter: false,
      resizable: false,
      suppressNavigable: true,
      suppressHeaderMenuButton: true,
      cellRenderer: 'bimLinkCellRenderer',
      cellClass: 'p-0',
    },
    {
      headerName: t('boq.description', { defaultValue: 'Description' }),
      field: 'description',
      // Description gets a heavier flex weight so it absorbs ~20% of viewport
      // even when 6+ regional-preset columns are visible. Keep a non-zero
      // minWidth so a flood of custom cols doesn't squeeze the BOQ text into
      // an unreadable sliver — but well below the previous 260 px floor that
      // forced horizontal overflow once 4–5 custom columns were added.
      minWidth: 180,
      flex: 3,
      editable: true,
      // Multi-line Langtext editor: a popup textarea so a position description
      // can hold a full LV-style specification with newlines, not just one
      // line. The value is the same `description` field (stored as TEXT,
      // newlines preserved); the grid's density toggle controls how much of it
      // shows at rest.
      cellEditor: 'agLargeTextCellEditor',
      cellEditorPopup: true,
      cellEditorParams: {
        maxLength: 5000,
        rows: 14,
        cols: 64,
      },
      cellRenderer: 'descriptionCellRenderer',
      // !pl-1 overrides AG Grid's default ~17px cell-horizontal-padding
      // so the position description sits flush-left within the column
      // (per UX request: remove the big empty indent on position rows).
      cellClass: (params) => {
        if (params.data?._isSection) return 'font-bold uppercase tracking-wide text-xs !pl-1 !pr-1';
        const ctx = params.context as { expandedPositions?: Set<string> } | undefined;
        const isExpanded = !!params.data?.id && (ctx?.expandedPositions?.has(params.data.id) ?? false);
        return isExpanded ? 'text-xs font-bold !pl-1 !pr-1' : 'text-xs !pl-1 !pr-1';
      },
      // Issue #136 — positions nested under a SUB-section get a left
      // indent proportional to their depth so the hierarchy is legible.
      // depth 0 (ungrouped) and depth 1 (under a top-level section) keep
      // the flush-left look; each deeper level shifts 18px right.
      cellStyle: (params) => {
        const d = params.data as Record<string, unknown> | undefined;
        if (
          !d || d._isSection || d._isFooter || d._isResource ||
          d._isAddResource || d._isVariantHeader
        ) {
          return null;
        }
        const depth = typeof d._depth === 'number' ? d._depth : 0;
        return depth > 1 ? { paddingLeft: `${(depth - 1) * 18}px` } : null;
      },
    },
    {
      headerName: t('boq.classification', { defaultValue: 'Code' }),
      field: 'classification',
      width: 100,
      hide: true,
      editable: false,
      valueGetter: (params) => {
        if (params.data?._isSection || params.data?._isFooter) return '';
        const cls = params.data?.classification;
        if (!cls || typeof cls !== 'object') return '';
        return cls.din276 || cls.nrm || cls.masterformat || '';
      },
      cellClass: 'text-xs font-mono text-content-secondary',
    },
    {
      headerName: t('boq.unit', { defaultValue: 'Unit' }),
      field: 'unit',
      width: 80,
      editable: (params) => !params.data?._isSection && !params.data?._isFooter,
      // Custom combobox: dropdown of standard SI / Cyrillic / labour
      // tokens + free-text input + auto-memory of custom values via
      // localStorage (so a unit typed once shows up in the dropdown
      // next time). Replaces the strict ``agSelectCellEditor`` whose
      // hard-coded list silently swallowed edits when the existing
      // value (e.g. "т", "маш.-ч") wasn't in the list.
      cellEditor: 'unitCellEditor',
      cellRenderer: 'unitCellRenderer',
      // StrictMode-proof commit path: the editor remounts up to 8x in
      // dev and AG Grid's ``getValue()`` may route through a stale
      // instance whose ``valueRef`` never saw the pick. ``valueSetter``
      // drains a module-scoped channel that the editor writes to BEFORE
      // ``stopEditing()`` fires, so the pick survives regardless of
      // which mount instance AG Grid queries. See ``__unitPickCommitChannel``
      // and ``unitColumnValueSetter`` in ``cellEditors.tsx``.
      valueSetter: (params: ValueSetterParams) => unitColumnValueSetter({
        data: params.data,
        newValue: params.newValue,
        oldValue: params.oldValue,
        node: params.node ? { id: params.node.id } : null,
        column: params.column ? { getColId: () => params.column!.getColId() } : null,
      }),
      // Let the UnitCellEditor's own keyboard handler own Enter / ArrowUp
      // / ArrowDown when it's editing. AG Grid 32 default would intercept
      // Enter at the grid level (capture phase) and call ``stopEditing``
      // before our React ``onKeyDown`` runs — that path reads ``getValue()``
      // on whatever React instance is current (often a stale StrictMode
      // mount whose ``valueRef`` never saw ``pick()``), and the user's
      // selection silently disappears. ``suppressKeyboardEvent`` opts out
      // of AG Grid's grid-level handling for these keys while editing,
      // letting our editor commit through ``pick()`` → channel → setter.
      suppressKeyboardEvent: (params) => {
        if (!params.editing) return false;
        const k = params.event.key;
        return k === 'Enter' || k === 'ArrowUp' || k === 'ArrowDown';
      },
      cellClass: 'text-center text-2xs font-mono',
      cellStyle: { display: 'flex', justifyContent: 'center', alignItems: 'center' },
    },
    {
      headerName: '',
      colId: '_bim_qty',
      field: '_bim_qty',
      width: 28,
      minWidth: 28,
      maxWidth: 28,
      editable: false,
      sortable: false,
      filter: false,
      resizable: false,
      suppressNavigable: true,
      suppressHeaderMenuButton: true,
      cellRenderer: 'bimQtyPickerCellRenderer',
      cellClass: 'p-0',
    },
    {
      headerName: t('boq.quantity', { defaultValue: 'Qty' }),
      field: 'quantity',
      width: 110,
      editable: (params) => !params.data?._isSection && !params.data?._isFooter && !params.data?._isResource,
      // Issue #90: Excel-style formulas in Qty (=2*PI()^2*3, =sqrt(144),
      // 12.5 x 4, …). The editor is CSP-safe (no eval); the resolved
      // numeric value goes into the column and the source formula is
      // persisted in metadata.formula via onFormulaApplied.
      cellEditor: 'formulaCellEditor',
      cellEditorPopup: true,
      cellEditorPopupPosition: 'over',
      cellRenderer: 'quantityCellRenderer',
      valueParser: (params) => {
        const val = parseFloat(params.newValue);
        return isNaN(val) ? params.oldValue : val;
      },
      // Surface the source formula in the AG Grid tooltip — much easier to
      // see than a tiny badge alone (Issue #90 follow-up).
      tooltipValueGetter: (params) => {
        const meta = params.data?.metadata as Record<string, unknown> | undefined;
        const f = meta?.formula;
        if (typeof f === 'string' && f) {
          return `Formula: ${f}\nClick to edit.`;
        }
        return undefined;
      },
      cellClass: (params) => {
        const base = 'text-right tabular-nums text-xs !pr-2 !pl-2';
        const ctx = params.context as { expandedPositions?: Set<string> } | undefined;
        const isExpanded = !!params.data?.id && (ctx?.expandedPositions?.has(params.data.id) ?? false);
        return isExpanded ? `${base} font-bold` : base;
      },
      headerClass: 'ag-right-aligned-header',
      type: 'numericColumn',
    },
    {
      headerName: t('boq.unit_rate', { defaultValue: 'Unit Rate' }),
      field: 'unit_rate',
      width: 130,
      editable: (params) => {
        if (params.data?._isSection || params.data?._isFooter) return false;
        // Position rate is the sum of resource subtotals — never editable
        // when the position carries resources. Variant rate edits happen
        // on the synthetic VARIANT row inside the resource panel and
        // patch ``metadata.variant.price`` only (see onUpdateVariantHeader
        // in BOQGrid). User design: "если есть ресурсы, не нужно трогать".
        const res = params.data?.metadata?.resources;
        if (Array.isArray(res) && res.length > 0) return false;
        return true;
      },
      cellEditor: 'agNumberCellEditor',
      cellEditorParams: { min: 0, precision: 2 },
      valueParser: (params) => {
        const val = parseFloat(params.newValue);
        return isNaN(val) ? params.oldValue : val;
      },
      // Custom renderer surfaces the inline CWICR variant picker pill when
      // the position carries `metadata.cost_item_variants` (cached at apply
      // time).  Falls through to a plain numeric span when no variants.
      cellRenderer: 'unitRateCellRenderer',
      cellClass: (params) => {
        let base = 'text-right tabular-nums text-xs !pr-2 !pl-2';
        const res = params.data?.metadata?.resources;
        if (Array.isArray(res) && res.length > 0) base = `${base} text-content-tertiary`;
        const ctx = params.context as { expandedPositions?: Set<string> } | undefined;
        const isExpanded = !!params.data?.id && (ctx?.expandedPositions?.has(params.data.id) ?? false);
        return isExpanded ? `${base} font-bold` : base;
      },
      headerClass: 'ag-right-aligned-header',
      type: 'numericColumn',
      tooltipValueGetter: (params) => {
        const res = params.data?.metadata?.resources;
        if (Array.isArray(res) && res.length > 0) {
          return t('boq.rate_from_resources', { defaultValue: 'Rate is calculated from resources. Edit individual resources to change.' });
        }
        return undefined;
      },
    },
    {
      // Header reflects the active display currency so users glancing
      // at the column never wonder which currency they're reading. When
      // displayCurrency is unset we keep the plain "Total" label.
      headerName: context.displayCurrency
        ? `${t('boq.total', { defaultValue: 'Total' })} (${context.displayCurrency.code})`
        : t('boq.total', { defaultValue: 'Total' }),
      field: 'total',
      width: 130,
      editable: false,
      // Compute total on-the-fly: for positions with resources, use
      // server-stored total; for positions without resources, always
      // show quantity × unit_rate so the user sees live updates.
      //
      // Issue #111 (multi-currency): when a position is priced in a
      // non-base currency (``metadata.currency`` set), the raw total is
      // in that currency. We rebase it into the project base currency
      // here so the column footer / directCost can sum mixed-currency
      // positions correctly. ``totalFormatter`` then applies the
      // optional displayCurrency override on top of the base value.
      valueGetter: (params) => {
        const d = params.data;
        if (!d || d._isFooter || d._isSection) return d?.total ?? 0;
        const meta = (d.metadata || d.metadata_ || {}) as Record<string, unknown>;
        const resources = meta.resources;
        const ctx = params.context as BOQColumnContext | undefined;
        if (Array.isArray(resources) && resources.length > 0) {
          // Resource-driven: server-computed total is authoritative.
          // Issue #111 (skolodi) — when any resource is priced in a
          // foreign currency the stored total mixes currencies (built
          // from Σ(r.qty×r.rate) with no FX); rebase per-resource so a
          // USD resource in an ARS project no longer reads "1 USD = 1 ARS".
          return resourceAwareTotalInBase(
            {
              total: d.total ?? 0,
              quantity: d.quantity,
              metadata: meta,
            },
            ctx?.currencyCode,
            ctx?.fxRates,
          );
        }
        // No resources: live compute quantity × unit_rate, then rebase
        // via the position-level metadata.currency (verified #131 path).
        const q = typeof d.quantity === 'number' ? d.quantity : parseFloat(d.quantity) || 0;
        const r = typeof d.unit_rate === 'number' ? d.unit_rate : parseFloat(d.unit_rate) || 0;
        const raw = q * r;
        const sourceCurrency = (meta.currency as string | undefined) || ctx?.currencyCode;
        return convertToBase(raw, sourceCurrency, ctx?.currencyCode, ctx?.fxRates);
      },
      valueFormatter: totalFormatter,
      cellClass: (params) => {
        const base = 'text-right tabular-nums text-xs !pr-2 !pl-2';
        if (params.data?._isSection) return `${base} font-bold`;
        if (params.data?._isFooter) return `${base} font-bold`;
        const ctx = params.context as { expandedPositions?: Set<string> } | undefined;
        const isExpanded = !!params.data?.id && (ctx?.expandedPositions?.has(params.data.id) ?? false);
        return isExpanded ? `${base} font-bold` : `${base} font-semibold`;
      },
      headerClass: 'ag-right-aligned-header',
      type: 'numericColumn',
    },
    {
      headerName: '',
      field: '_actions',
      width: 44,
      editable: false,
      sortable: false,
      filter: false,
      cellRenderer: 'actionsCellRenderer',
      suppressHeaderMenuButton: true,
      cellClass: 'flex items-center justify-center',
    },
  ];
}

/* ── Custom column definitions from BOQ metadata ──────────────────────── */

export interface CustomColumnDef {
  name: string;
  display_name: string;
  column_type: 'text' | 'number' | 'date' | 'select' | 'calculated';
  options?: string[];
  sort_order?: number;
  /** Formula source for `calculated` columns. e.g. `=quantity * unit_rate * 1.19`. */
  formula?: string;
  /** Display decimals for `calculated` columns when result is numeric. */
  decimals?: number;
  /**
   * Semantic hint for region-specific number columns. When set, the column
   * is rendered read-only and its value is auto-derived from the position
   * (no manual entry, no `metadata.custom_fields` write).
   *
   *   - `resource_sum`  — sum of `metadata.resources[]` whose `type`
   *                       matches `resource_role`. Used for GAEB EP-split
   *                       columns (Lohn-EP / Material-EP / Geräte-EP).
   *
   *   - `percentage_of_unit_rate` — share of `unit_rate` that comes from
   *     resources of type `resource_role`, expressed as a percent
   *     (0–100). Used for ÖNORM "Lohn-Anteil %" etc.
   *
   * `column_type` stays `number` so existing AG-Grid number behaviour
   * (right-align, tabular nums, formatting) applies. The flag is
   * forwarded through the backend untouched.
   */
  derived?: 'resource_sum' | 'percentage_of_unit_rate';
  /**
   * Resource type filter for `derived` columns. Matches the `type` field
   * on `position.metadata.resources[]` (one of: 'material' | 'labor' |
   * 'equipment' | 'operator' | 'subcontractor' | 'other'). Ignored when
   * `derived` is unset. Accepts either a single role or a list — the
   * GAEB Sonstiges-EP preset uses ``['other', 'operator', 'subcontractor']``
   * to keep Lohn + Material + Geräte + Sonstiges = unit_rate when a
   * position carries operator / subcontractor resources.
   */
  resource_role?:
    | 'material'
    | 'labor'
    | 'equipment'
    | 'operator'
    | 'subcontractor'
    | 'other'
    | Array<'material' | 'labor' | 'equipment' | 'operator' | 'subcontractor' | 'other'>;
}

/**
 * Optional engine context for `calculated` columns. When supplied, the
 * column's valueGetter evaluates the formula against these positions and
 * variables; otherwise calculated columns render `''` (no engine = nothing
 * to evaluate). Text/number/date/select columns ignore this argument and
 * keep their original behaviour.
 */
export interface CustomColumnEngineContext {
  positions: Position[];
  variables?: Map<string, FormulaVariable>;
}

/**
 * Format a numeric formula result for display. Mirrors the rounding the
 * engine already applies (4-decimal max via `evaluateFormulaRaw`) but lets
 * the column author choose presentation precision separately.
 */
function formatCalculatedNumber(value: number, decimals: number): string {
  const safe = Math.max(0, Math.min(6, decimals));
  return value.toFixed(safe);
}

/**
 * Build a `FormulaContext` for the row currently being rendered. Every
 * calculated cell needs the WHOLE positions list (so `pos("01.001")` can
 * resolve other rows) plus the row's own field values exposed through
 * `col("name")` and the bare identifiers `quantity` / `unit_rate` /
 * `total`. We project the latter into `currentRow` AND inject them as
 * read-only $variables — `quantity` / `unit_rate` are already valid
 * identifiers in the engine grammar (no leading `$`), so we wrap them in
 * a synthetic context shape: bare identifiers go through the `col(...)`
 * lookup path the engine already supports.
 *
 * We deliberately DON'T mutate the shared variables map here; we clone
 * it and overlay the row-scoped overrides so concurrent renders don't
 * race.
 */
function buildRowFormulaContext(
  row: Record<string, unknown> | undefined,
  engineCtx: CustomColumnEngineContext,
): FormulaContext {
  const row_ = row ?? {};
  const variables = new Map<string, FormulaVariable>(engineCtx.variables ?? new Map());
  // Expose the current row's measure / rate / total as $-variables so the
  // user can write `=quantity * unit_rate * 1.19` without having to pull
  // them through `col()`. Names are uppercased to match the engine's
  // canonical $VAR convention.
  const q = typeof row_.quantity === 'number' ? row_.quantity : parseFloat(String(row_.quantity ?? ''));
  const r = typeof row_.unit_rate === 'number' ? row_.unit_rate : parseFloat(String(row_.unit_rate ?? ''));
  const tot = typeof row_.total === 'number' ? row_.total : parseFloat(String(row_.total ?? ''));
  if (!isNaN(q)) variables.set('QUANTITY', { type: 'number', value: q });
  if (!isNaN(r)) variables.set('UNIT_RATE', { type: 'number', value: r });
  if (!isNaN(tot)) variables.set('TOTAL', { type: 'number', value: tot });
  return buildFormulaContext({
    positions: engineCtx.positions,
    variables,
    currentPositionId: typeof row_.id === 'string' ? row_.id : undefined,
    currentRow: row_,
  });
}

/**
 * valueGetter factory for a `calculated` column. Returns the formatted
 * formula result, or one of the sentinel error markers:
 *   • `#ERR`   — syntax / runtime error (unknown function, type mismatch, …)
 *   • `#CYCLE` — formula transitively references its own column
 *
 * Cycle detection is best-effort here: the BOQ-level dependency graph
 * already covers `pos(...)` cycles, but a calculated column that calls
 * `col("self_name")` would self-loop. We guard that one case explicitly.
 */
function makeCalculatedValueGetter(
  col: CustomColumnDef,
  engineCtx: CustomColumnEngineContext,
): (params: ValueGetterParams) => string {
  const formula = col.formula ?? '';
  const decimals = col.decimals ?? 2;
  return (params: ValueGetterParams): string => {
    const data = params.data as Record<string, unknown> | undefined;
    if (!data) return '';
    if (data._isSection || data._isFooter) return '';
    if (!isFormula(formula)) return '';
    // Self-reference guard: `col("X")` inside column X's own formula.
    if (formula.includes(`col("${col.name}")`) || formula.includes(`col('${col.name}')`)) {
      return '#CYCLE';
    }
    try {
      const ctx = buildRowFormulaContext(data, engineCtx);
      const result = evaluateFormulaStrict(formula, ctx);
      if (result === null) return '';
      if (typeof result === 'number') return formatCalculatedNumber(result, decimals);
      if (typeof result === 'boolean') return result ? '1' : '0';
      return String(result);
    } catch {
      return '#ERR';
    }
  };
}

export function getCustomColumnDefs(
  customColumns: CustomColumnDef[],
  engineCtx?: CustomColumnEngineContext,
): ColDef[] {
  // Default empty engine context — calculated columns simply render '' if
  // no positions / variables are wired in. This keeps the call-site
  // backwards compatible for callers that don't yet supply context.
  const ctx: CustomColumnEngineContext = engineCtx ?? { positions: [] };
  // O(1) parent lookup for resource rows. Resource rows carry
  // ``_parentPositionId`` but no ``metadata`` of their own — to render
  // a parent-position custom field on a sub-row we have to grab the
  // parent's metadata at value-getter time. Built once per column-defs
  // rebuild, not per cell render.
  const positionsById = new Map<string, Position>();
  for (const p of ctx.positions) {
    if (p.id) positionsById.set(p.id, p);
  }
  return customColumns
    .slice()
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
    .map((col) => {
      // Migration: legacy rows without `column_type` default to 'text'.
      const colType: CustomColumnDef['column_type'] = col.column_type ?? 'text';
      const isCalculated = colType === 'calculated';
      const isNumeric = colType === 'number' || isCalculated;

      // Stable widths so adding 5–10 columns from a regional preset doesn't
      // explode the grid horizontally. AG Grid still respects the user's
      // resize via `resizable: true` (set on defaultColDef in BOQGrid).
      // We keep `field` set to the same string as `colId` purely as an
      // identifier — the actual data lives at
      // `data.metadata.custom_fields[col.name]` and is read/written via
      // the valueGetter / valueSetter below. AG Grid never falls back to
      // direct field-based access when both getters are present, so the
      // chosen field string can never collide with anything on `data`.
      const isDerived = col.derived === 'resource_sum' || col.derived === 'percentage_of_unit_rate';
      const base: ColDef = {
        headerName: isCalculated ? `ƒ ${col.display_name}` : col.display_name,
        field: `custom_${col.name}`,
        colId: `custom_${col.name}`,
        // Compact defaults — a regional preset can add up to 6 columns at
        // once, so each one needs to fit on a normal laptop without
        // pushing standard columns off-screen. Users can still drag the
        // column edge wider thanks to `resizable: true` (defaultColDef).
        // ``flex: 1`` lets sizeColumnsToFit shrink each custom col evenly
        // when 4-6 of them are added — combined with the heavier flex
        // weight on the description column the BOQ no longer overflows
        // horizontally on a normal laptop screen.
        width: colType === 'text' ? 110 : 90,
        minWidth: 56,  // ~3 chars header + padding (per UX spec)
        maxWidth: 320,
        flex: 1,
        // Derived columns are computed from position.metadata.resources —
        // never editable. Marking them readOnly lines them up visually
        // with the existing read-only "Total" column.
        // Resource rows are editable for non-derived custom columns —
        // values flow into ``parent.metadata.resources[i].metadata.custom_fields[name]``
        // so each resource can carry its own supplier / lead time / QC status
        // independent of the parent position. Derived (resource_sum /
        // percentage_of_unit_rate) and calculated (formula) columns stay
        // read-only because their value is auto-computed.
        editable: isCalculated || isDerived
          ? false
          : (params) =>
              !params.data?._isSection &&
              !params.data?._isFooter &&
              !params.data?._isAddResource,
        // ``cellClass`` is a function so we can mute the styling on
        // resource sub-rows — those cells either inherit from the
        // parent (text/number custom fields) or break a position-level
        // total down per resource (derived columns). Either way the
        // value is computed, not user-entered, so we render it with
        // the same subdued treatment AG Grid already uses for other
        // read-only derived cells.
        cellClass: (params) => {
          const isResourceRow = !!params.data?._isResource;
          // Resource rows for derived/calculated cells stay muted+italic —
          // those values are still computed. Non-derived custom cols on
          // resources are now editable per-resource, so they read like
          // normal editable cells (no italic, no muted tone).
          const computedOnResource = isResourceRow && (isCalculated || isDerived);
          if (isNumeric) {
            const tone =
              isCalculated || isDerived || computedOnResource
                ? 'text-content-secondary'
                : '';
            const italic = computedOnResource ? 'italic' : '';
            return `text-right tabular-nums text-xs ${tone} ${italic}`.trim();
          }
          return computedOnResource ? 'text-xs italic text-content-tertiary' : 'text-xs';
        },
        headerClass: isNumeric ? 'ag-right-aligned-header' : '',
      };

      if (isCalculated) {
        base.valueGetter = makeCalculatedValueGetter(col, ctx);
        // Formula result IS the display value — no further formatting.
        base.valueFormatter = (params: ValueFormatterParams) =>
          typeof params.value === 'string' ? params.value : '';
        base.tooltipValueGetter = (params) => {
          const v = params.value;
          if (v === '#CYCLE') {
            return 'This calculated column references itself - cycle detected.';
          }
          if (v === '#ERR') {
            return `Formula error in "${col.formula ?? ''}". Open Custom Columns to edit.`;
          }
          return col.formula ? `Formula: ${col.formula}` : undefined;
        };
        return base;
      }

      // Derived columns (GAEB Lohn/Material/Geräte EP, ÖNORM
      // Lohn-Anteil %) auto-compute from `metadata.resources[]` so the
      // user never has to retype values that already live on the
      // position. The valueGetter sums or proportions resources of the
      // declared `resource_role` and the column is marked read-only
      // above. valueSetter is NOT installed — AG Grid will not fire
      // edits on a non-editable cell, so the field is simply display.
      if (isDerived) {
        const role = col.resource_role;
        // Normalize role to a Set so single / array forms match identically
        // (Sonstiges-EP carries ``['other', 'operator', 'subcontractor']``).
        const roleSet: Set<string> | null = role
          ? new Set(Array.isArray(role) ? role : [role])
          : null;
        const matchesRole = (t: string): boolean => !roleSet || roleSet.has(t);
        const dec = Math.max(0, Math.min(6, col.decimals ?? 2));
        base.valueGetter = (params) => {
          const data = params.data;
          if (!data || data._isSection || data._isFooter || data._isAddResource) {
            return '';
          }

          // Resource sub-row: render the per-resource value (its own
          // qty × rate contribution, OR its own % of the parent
          // position's total resource sum). Only resources whose type
          // matches the column's role filter render a value — others
          // stay blank so the column visually attributes the
          // contribution to the right resource.
          if (data._isResource) {
            const t = typeof data._resourceType === 'string' ? data._resourceType : 'other';
            if (!matchesRole(t)) return '';
            const q = typeof data._resourceQty === 'number'
              ? data._resourceQty
              : parseFloat(String(data._resourceQty ?? '0')) || 0;
            const r = typeof data._resourceRate === 'number'
              ? data._resourceRate
              : parseFloat(String(data._resourceRate ?? '0')) || 0;
            const contribution = q * r;
            if (col.derived === 'percentage_of_unit_rate') {
              const parent = data._parentPositionId
                ? positionsById.get(String(data._parentPositionId))
                : undefined;
              const parentResources =
                ((parent?.metadata as Record<string, unknown> | undefined)
                  ?.resources as Array<Record<string, unknown>> | undefined) ?? [];
              let allSum = 0;
              for (const res of parentResources) {
                const rq = typeof res.quantity === 'number'
                  ? res.quantity
                  : parseFloat(String(res.quantity ?? '0')) || 0;
                const rr = typeof res.unit_rate === 'number'
                  ? res.unit_rate
                  : parseFloat(String(res.unit_rate ?? '0')) || 0;
                allSum += rq * rr;
              }
              if (allSum <= 0) return '';
              return ((contribution / allSum) * 100).toFixed(dec);
            }
            // resource_sum on a resource row = this resource's
            // contribution to the position unit rate.
            return contribution.toFixed(dec);
          }

          // Position row: existing aggregation across the position's
          // resources. Sums the per-unit subtotal of resources whose
          // `type` matches the role hint.
          const meta = (data.metadata as Record<string, unknown> | undefined) ?? {};
          const resources = (meta.resources as Array<Record<string, unknown>> | undefined) ?? [];
          if (!Array.isArray(resources) || resources.length === 0) return '';
          let matched = 0;
          let allSum = 0;
          for (const res of resources) {
            const t = typeof res.type === 'string' ? res.type : 'other';
            const q = typeof res.quantity === 'number' ? res.quantity : parseFloat(String(res.quantity ?? '0')) || 0;
            const r = typeof res.unit_rate === 'number' ? res.unit_rate : parseFloat(String(res.unit_rate ?? '0')) || 0;
            const contribution = q * r;
            allSum += contribution;
            if (matchesRole(t)) matched += contribution;
          }
          if (col.derived === 'percentage_of_unit_rate') {
            if (allSum <= 0) return '';
            const pct = (matched / allSum) * 100;
            return pct.toFixed(dec);
          }
          // resource_sum
          return matched.toFixed(dec);
        };
        const roleLabel = roleSet ? Array.from(roleSet).join(' / ') : 'matching';
        base.tooltipValueGetter = () => {
          if (col.derived === 'percentage_of_unit_rate') {
            return `${col.display_name} - share of unit rate from ${roleLabel} resources (auto-computed; edit resources to change)`;
          }
          return `${col.display_name} - sum of ${roleLabel} resources for this position (auto-computed; edit resources to change)`;
        };
        return base;
      }

      // Non-calculated columns read/write through `metadata.custom_fields`
      // keyed by the column's STORED `name` (captured in closure on
      // every rebuild — never derived from grid-level identifiers like
      // `field` / `colId` that the user might rename later). Keeping
      // these two as the SINGLE source of truth eliminates the
      // "values jump to a sibling column" class of bugs entirely.
      //
      // Resource sub-rows inherit the parent position's custom-field
      // value — they have no `metadata` of their own, so we look the
      // parent up by ``_parentPositionId``. This makes the column
      // visible across all rows of a position; the cell is read-only on
      // sub-rows (see editable above) so edits still happen at the
      // position level.
      base.valueGetter = (params) => {
        const data = params.data;
        if (!data) return '';
        // Resource sub-row — try the per-resource value first
        // (``parent.metadata.resources[i].metadata.custom_fields[name]``),
        // fall back to the parent position's value so a "globally true"
        // value (supplier set on the position) still shows on each
        // resource row that hasn't been overridden.
        if (data._isResource && data._parentPositionId) {
          const parent = positionsById.get(String(data._parentPositionId));
          const resIdx = typeof data._resourceIndex === 'number' ? data._resourceIndex : -1;
          if (resIdx >= 0) {
            const parentMeta = parent?.metadata as Record<string, unknown> | undefined;
            const resources = (parentMeta?.resources as Array<Record<string, unknown>> | undefined) ?? [];
            if (resIdx < resources.length) {
              const resMeta = resources[resIdx]?.metadata as Record<string, unknown> | undefined;
              const resCf = resMeta?.custom_fields as Record<string, unknown> | undefined;
              const resVal = resCf?.[col.name];
              if (resVal !== undefined && resVal !== null && resVal !== '') {
                return resVal;
              }
            }
          }
          const parentMeta = parent?.metadata as Record<string, unknown> | undefined;
          const parentCf = parentMeta?.custom_fields as Record<string, unknown> | undefined;
          return parentCf?.[col.name] ?? '';
        }
        // Position row
        const meta = data.metadata as Record<string, unknown> | undefined;
        const cf = meta?.custom_fields as Record<string, unknown> | undefined;
        return cf?.[col.name] ?? '';
      };
      // valueSetter rebuilds `metadata` and `custom_fields` as fresh
      // objects rather than mutating in place. Mutation worked, but it
      // made every edit silently mutate the React Query cache, which in
      // turn caused stale cell renders when a sibling column was
      // re-evaluated against the same row right after a cell commit.
      // Immutable updates are how the rest of the grid handles row
      // edits (see onCellValueChanged in BOQGrid.tsx) — bringing the
      // setter in line keeps the data flow uniform.
      base.valueSetter = (params) => {
        if (!params.data) return false;
        const meta = (params.data.metadata as Record<string, unknown> | undefined) ?? {};
        const cf = (meta.custom_fields as Record<string, unknown> | undefined) ?? {};
        if (cf[col.name] === params.newValue) return false;
        params.data.metadata = {
          ...meta,
          custom_fields: { ...cf, [col.name]: params.newValue },
        };
        return true;
      };

      if (colType === 'number') {
        base.cellEditor = 'agNumberCellEditor';
        base.valueParser = (params) => {
          const val = parseFloat(params.newValue);
          return isNaN(val) ? '' : val;
        };
      } else if (colType === 'select' && col.options?.length) {
        base.cellEditor = 'agSelectCellEditor';
        base.cellEditorParams = { values: ['', ...col.options] };
      } else {
        base.cellEditor = 'agTextCellEditor';
      }

      return base;
    });
}
