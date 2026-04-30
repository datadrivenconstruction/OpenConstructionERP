import type { ColDef, ValueFormatterParams, ValueGetterParams } from 'ag-grid-community';
import { fmtWithCurrency } from '../boqHelpers';
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
          ? `${params.rowNode.data.ordinal} — ${params.rowNode.data.description ?? ''}`
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
      width: 28,
      minWidth: 28,
      maxWidth: 28,
      editable: false,
      sortable: false,
      filter: false,
      resizable: false,
      suppressNavigable: true,
      suppressHeaderMenuButton: true,
      cellRenderer: 'expandCellRenderer',
      cellClass: 'p-0',
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
      minWidth: 260,
      flex: 1,
      editable: true,
      cellEditor: 'agTextCellEditor',
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
      headerName: t('boq.total', { defaultValue: 'Total' }),
      field: 'total',
      width: 130,
      editable: false,
      // Compute total on-the-fly: for positions with resources, use
      // server-stored total; for positions without resources, always
      // show quantity × unit_rate so the user sees live updates.
      valueGetter: (params) => {
        const d = params.data;
        if (!d || d._isFooter || d._isSection) return d?.total ?? 0;
        const meta = (d.metadata || d.metadata_ || {}) as Record<string, unknown>;
        const resources = meta.resources;
        if (Array.isArray(resources) && resources.length > 0) {
          // Resource-driven: server-computed total is authoritative
          return d.total ?? 0;
        }
        // No resources: live compute quantity × unit_rate
        const q = typeof d.quantity === 'number' ? d.quantity : parseFloat(d.quantity) || 0;
        const r = typeof d.unit_rate === 'number' ? d.unit_rate : parseFloat(d.unit_rate) || 0;
        return q * r;
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
  return customColumns
    .slice()
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
    .map((col) => {
      // Migration: legacy rows without `column_type` default to 'text'.
      const colType: CustomColumnDef['column_type'] = col.column_type ?? 'text';
      const isCalculated = colType === 'calculated';
      const isNumeric = colType === 'number' || isCalculated;

      const base: ColDef = {
        headerName: isCalculated ? `ƒ ${col.display_name}` : col.display_name,
        field: `_custom_${col.name}`,
        colId: `custom_${col.name}`,
        width: colType === 'text' ? 140 : 110,
        editable: isCalculated
          ? false
          : (params) => !params.data?._isSection && !params.data?._isFooter,
        cellClass: isNumeric
          ? isCalculated
            ? 'text-right tabular-nums text-xs text-content-secondary'
            : 'text-right tabular-nums text-xs'
          : 'text-xs',
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
            return 'This calculated column references itself — cycle detected.';
          }
          if (v === '#ERR') {
            return `Formula error in "${col.formula ?? ''}". Open Custom Columns to edit.`;
          }
          return col.formula ? `Formula: ${col.formula}` : undefined;
        };
        return base;
      }

      // Non-calculated columns: same valueGetter / valueSetter as before.
      base.valueGetter = (params) => {
        const cf = (params.data?.metadata as Record<string, unknown> | undefined)
          ?.custom_fields as Record<string, unknown> | undefined;
        return cf?.[col.name] ?? '';
      };
      base.valueSetter = (params) => {
        if (!params.data) return false;
        if (!params.data.metadata) params.data.metadata = {};
        if (!params.data.metadata.custom_fields) params.data.metadata.custom_fields = {};
        (params.data.metadata.custom_fields as Record<string, unknown>)[col.name] = params.newValue;
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
