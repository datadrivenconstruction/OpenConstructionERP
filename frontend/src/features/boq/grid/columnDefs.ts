import type { ColDef, ValueFormatterParams } from 'ag-grid-community';
import { fmtWithCurrency } from '../boqHelpers';

export interface BOQColumnContext {
  currencySymbol: string;
  currencyCode: string;
  locale: string;
  fmt: Intl.NumberFormat;
  t: (key: string, opts?: Record<string, string>) => string;
}

function currencyFormatter(params: ValueFormatterParams): string {
  const ctx = params.context as BOQColumnContext | undefined;
  if (params.value == null || params.data?._isSection || params.data?._isFooter) return '';
  const fmt = ctx?.fmt ?? new Intl.NumberFormat('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return fmt.format(params.value);
}

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
      width: 36,
      maxWidth: 36,
      minWidth: 36,
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
      headerName: t('boq.ordinal', { defaultValue: 'Pos.' }),
      field: 'ordinal',
      width: 120,
      minWidth: 90,
      editable: (params) => {
        if (params.data?._isSection || params.data?._isFooter) return false;
        // Positions with resources use the chevron in ordinal cell — disable editing
        // so singleClickEdit doesn't swallow the click event
        const res = params.data?.metadata?.resources;
        if (Array.isArray(res) && res.length > 0) return false;
        return true;
      },
      cellClass: 'font-mono text-xs',
    },
    {
      headerName: t('boq.description', { defaultValue: 'Description' }),
      field: 'description',
      minWidth: 260,
      flex: 1,
      editable: (params) => !params.data?._isFooter,
      cellEditor: 'agTextCellEditor',
      cellClass: (params) => {
        if (params.data?._isSection) return 'font-bold uppercase tracking-wide text-xs';
        return 'text-xs';
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
      cellEditor: 'agTextCellEditor',
      cellEditorParams: { useFormatter: false },
      cellClass: 'text-center text-2xs font-mono uppercase',
    },
    {
      headerName: t('boq.quantity', { defaultValue: 'Qty' }),
      field: 'quantity',
      width: 100,
      editable: (params) => !params.data?._isSection && !params.data?._isFooter,
      cellEditor: 'agNumberCellEditor',
      cellEditorParams: { min: 0, precision: 4 },
      valueFormatter: currencyFormatter,
      valueParser: (params) => {
        const val = parseFloat(params.newValue);
        return isNaN(val) ? params.oldValue : val;
      },
      cellClass: 'text-right tabular-nums text-xs',
      headerClass: 'ag-right-aligned-header',
      type: 'numericColumn',
    },
    {
      headerName: t('boq.unit_rate', { defaultValue: 'Unit Rate' }),
      field: 'unit_rate',
      width: 110,
      editable: (params) => {
        if (params.data?._isSection || params.data?._isFooter) return false;
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
      valueFormatter: currencyFormatter,
      cellClass: (params) => {
        const base = 'text-right tabular-nums text-xs';
        const res = params.data?.metadata?.resources;
        if (Array.isArray(res) && res.length > 0) return `${base} text-content-tertiary`;
        return base;
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
        const base = 'text-right tabular-nums text-xs';
        if (params.data?._isSection) return `${base} font-bold`;
        if (params.data?._isFooter) return `${base} font-bold`;
        return `${base} font-semibold`;
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
  column_type: 'text' | 'number' | 'date' | 'select';
  options?: string[];
  sort_order?: number;
}

export function getCustomColumnDefs(customColumns: CustomColumnDef[]): ColDef[] {
  return customColumns
    .slice()
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
    .map((col) => {
      const base: ColDef = {
        headerName: col.display_name,
        field: `_custom_${col.name}`,
        colId: `custom_${col.name}`,
        width: col.column_type === 'text' ? 140 : 100,
        editable: (params) => !params.data?._isSection && !params.data?._isFooter,
        cellClass: col.column_type === 'number' ? 'text-right tabular-nums text-xs' : 'text-xs',
        headerClass: col.column_type === 'number' ? 'ag-right-aligned-header' : '',
        valueGetter: (params) => {
          const cf = params.data?.metadata?.custom_fields;
          return cf?.[col.name] ?? '';
        },
        valueSetter: (params) => {
          if (!params.data) return false;
          if (!params.data.metadata) params.data.metadata = {};
          if (!params.data.metadata.custom_fields) params.data.metadata.custom_fields = {};
          params.data.metadata.custom_fields[col.name] = params.newValue;
          return true;
        },
      };

      if (col.column_type === 'number') {
        base.cellEditor = 'agNumberCellEditor';
        base.valueParser = (params) => {
          const val = parseFloat(params.newValue);
          return isNaN(val) ? '' : val;
        };
      } else if (col.column_type === 'select' && col.options?.length) {
        base.cellEditor = 'agSelectCellEditor';
        base.cellEditorParams = { values: ['', ...col.options] };
      } else {
        base.cellEditor = 'agTextCellEditor';
      }

      return base;
    });
}
