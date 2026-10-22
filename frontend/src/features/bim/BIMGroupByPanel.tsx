// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMGroupByPanel - ad hoc grouping of the filtered model.
 *
 * Pick a property (and optionally a second one) and the elements that pass
 * the active filters are grouped with counts and summed length / area /
 * volume. Clicking a group isolates and selects it in 3D, "Colour by group"
 * paints each group in the model with the legend colour, and the table
 * exports to CSV or Excel. Everything here is client-side, so it works on a
 * read-only deployment too.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import * as THREE from 'three';
import { ChevronDown, ChevronRight, Download, Eye, FileSpreadsheet, MousePointerClick, Palette } from 'lucide-react';
import type { BIMElementData, ElementManager } from '@/shared/ui/BIMViewer';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { triggerDownload } from '@/shared/lib/api';
import {
  BUILTIN_GROUP_KEYS,
  buildGroupTree,
  colourForIndex,
  discoverPropertyKeys,
  groupExportRows,
  groupsToCsv,
  groupValueOf,
  totalsOf,
  type GroupExportLabels,
  type GroupKey,
  type GroupNode,
  type GroupTotals,
} from './bimGrouping';

export interface BIMGroupByPanelProps {
  /** Elements that pass the active filters. */
  elements: BIMElementData[];
  /** Whether the model elements are still loading. */
  isLoading?: boolean;
  /** Isolate these element ids in 3D. */
  onIsolate: (ids: string[]) => void;
  /** Select these element ids in 3D. */
  onSelect: (ids: string[]) => void;
  /** Model name for export file names. */
  modelName?: string;
  /** Whether every parameter is loaded; otherwise only the grouping subset. */
  propertiesLoaded?: boolean;
  propertiesLoading?: boolean;
  onLoadProperties?: () => void;
}

function elementManager(): ElementManager | null {
  const w = window as unknown as { __oeBim?: { elementManager?: ElementManager | null } };
  return w.__oeBim?.elementManager ?? null;
}

export default function BIMGroupByPanel({
  elements,
  isLoading,
  onIsolate,
  onSelect,
  modelName,
  propertiesLoaded = true,
  propertiesLoading,
  onLoadProperties,
}: BIMGroupByPanelProps) {
  const { t } = useTranslation();
  const q = useDisplayQuantity();
  const [level1, setLevel1] = useState<GroupKey>('category');
  const [level2, setLevel2] = useState<GroupKey | ''>('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [colourOn, setColourOn] = useState(false);

  const builtinLabel = useCallback(
    (key: GroupKey): string => {
      switch (key) {
        case 'category':
          return t('bim.groupby.key_category', { defaultValue: 'Category' });
        case 'level':
          return t('bim.groupby.key_level', { defaultValue: 'Level' });
        case 'type':
          return t('bim.groupby.key_type', { defaultValue: 'Type' });
        case 'family':
          return t('bim.groupby.key_family', { defaultValue: 'Family' });
        case 'material':
          return t('bim.groupby.key_material', { defaultValue: 'Material' });
        case 'ifc_class':
          return t('bim.groupby.key_ifc_class', { defaultValue: 'IFC class' });
        case 'discipline':
          return t('bim.groupby.key_discipline', { defaultValue: 'Discipline' });
        default:
          return key.slice('prop:'.length);
      }
    },
    [t],
  );

  // Only offer built-in keys that some element actually carries, so the
  // list never invites a grouping that collapses everything into "(not set)".
  const availableBuiltins = useMemo(
    () => BUILTIN_GROUP_KEYS.filter((k) => elements.some((el) => groupValueOf(el, k) !== '')),
    [elements],
  );
  const customKeys = useMemo(() => discoverPropertyKeys(elements), [elements]);

  useEffect(() => {
    if (availableBuiltins.length > 0 && !level1.startsWith('prop:') && !availableBuiltins.includes(level1 as never)) {
      setLevel1(availableBuiltins[0]!);
    }
  }, [availableBuiltins, level1]);

  const nested = level2 !== '' && level2 !== level1;
  const tree = useMemo(
    () => buildGroupTree(elements, level1, nested ? (level2 as GroupKey) : null),
    [elements, level1, level2, nested],
  );
  const totals = useMemo(() => totalsOf(tree), [tree]);

  // Colour by group: paint level-1 groups with their legend colour.
  useEffect(() => {
    const mgr = elementManager();
    if (!mgr) return;
    if (!colourOn) return;
    const colours = new Map<string, THREE.Color>();
    tree.forEach((node, i) => {
      const c = new THREE.Color(colourForIndex(i));
      for (const id of node.ids) colours.set(id, c);
    });
    mgr.colorByDirect((el) => colours.get(el.id) ?? null);
    return () => {
      elementManager()?.resetColors();
    };
  }, [colourOn, tree]);

  const fmtNum = useCallback(
    (v: number) => v.toLocaleString(getNumberLocale(), { maximumFractionDigits: v >= 100 ? 0 : 2 }),
    [],
  );
  const qtyText = useCallback(
    (g: GroupTotals): string[] => {
      const out: string[] = [];
      if (g.length > 0) {
        const v = q.convert(g.length, 'm');
        out.push(`${fmtNum(v.value)} ${v.unit}`);
      }
      if (g.area > 0) {
        const v = q.convert(g.area, 'm²');
        out.push(`${fmtNum(v.value)} ${v.unit}`);
      }
      if (g.volume > 0) {
        const v = q.convert(g.volume, 'm³');
        out.push(`${fmtNum(v.value)} ${v.unit}`);
      }
      return out;
    },
    [q, fmtNum],
  );

  const notSet = t('bim.groupby.not_set', { defaultValue: '(not set)' });

  const activate = useCallback(
    (node: GroupNode) => {
      if (activeId === node.id) {
        setActiveId(null);
        onIsolate([]);
        onSelect([]);
        return;
      }
      setActiveId(node.id);
      onIsolate(node.ids);
      onSelect(node.ids);
    },
    [activeId, onIsolate, onSelect],
  );

  const toggleExpanded = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const exportLabels = useMemo<GroupExportLabels>(
    () => ({
      level1: builtinLabel(level1),
      level2: nested ? builtinLabel(level2 as GroupKey) : undefined,
      count: t('bim.groupby.col_count', { defaultValue: 'Count' }),
      length: t('bim.groupby.col_length', { defaultValue: 'Length (m)' }),
      area: t('bim.groupby.col_area', { defaultValue: 'Area (m2)' }),
      volume: t('bim.groupby.col_volume', { defaultValue: 'Volume (m3)' }),
      notSet,
      total: t('bim.groupby.total', { defaultValue: 'Total' }),
    }),
    [builtinLabel, level1, level2, nested, notSet, t],
  );
  const fileBase = `${(modelName || 'model').replace(/[^\w.-]+/g, '_')}_groups`;

  const exportCsv = useCallback(() => {
    const csv = groupsToCsv(tree, exportLabels, nested);
    triggerDownload(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }), `${fileBase}.csv`);
  }, [tree, exportLabels, nested, fileBase]);

  const exportXlsx = useCallback(async () => {
    const mod = await import('exceljs');
    const Ctor = (mod.Workbook ?? mod.default.Workbook) as typeof import('exceljs').Workbook;
    const wb = new Ctor();
    const ws = wb.addWorksheet(t('bim.groupby.sheet_name', { defaultValue: 'Groups' }).slice(0, 31));
    const header = [
      exportLabels.level1,
      ...(nested ? [exportLabels.level2 ?? ''] : []),
      exportLabels.count,
      exportLabels.length,
      exportLabels.area,
      exportLabels.volume,
    ];
    ws.addRow(header).font = { bold: true };
    const rows = groupExportRows(tree, exportLabels, nested);
    rows.forEach((r, i) => {
      const row = ws.addRow([r.level1, ...(nested ? [r.level2 ?? ''] : []), r.count, r.length, r.area, r.volume]);
      if (i === rows.length - 1) row.font = { bold: true };
    });
    ws.columns.forEach((col, i) => {
      col.width = i < (nested ? 2 : 1) ? 32 : 14;
    });
    const buf = await wb.xlsx.writeBuffer();
    triggerDownload(
      new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
      `${fileBase}.xlsx`,
    );
  }, [tree, exportLabels, nested, fileBase, t]);

  const selectClass =
    'w-full min-w-0 text-[11px] py-1 px-1.5 rounded border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue';

  const keyOptions = (
    <>
      <optgroup label={t('bim.groupby.builtin_props', { defaultValue: 'Model properties' })}>
        {availableBuiltins.map((k) => (
          <option key={k} value={k}>
            {builtinLabel(k)}
          </option>
        ))}
      </optgroup>
      {customKeys.length > 0 && (
        <optgroup label={t('bim.groupby.custom_props', { defaultValue: 'Parameters' })}>
          {customKeys.map((k) => (
            <option key={k} value={`prop:${k}`}>
              {k}
            </option>
          ))}
        </optgroup>
      )}
    </>
  );

  const renderRow = (node: GroupNode, depth: 0 | 1, colour: string | null, hasChildren: boolean) => {
    const isOpen = expanded.has(node.id);
    const isActive = activeId === node.id;
    const quantities = qtyText(node);
    return (
      <div
        key={node.id}
        className={`flex items-start gap-1 pe-2 ${depth === 1 ? 'ps-6' : 'ps-1'} py-1 ${
          isActive ? 'bg-oe-blue/10' : 'hover:bg-surface-secondary'
        }`}
        data-testid={depth === 0 ? 'bim-groupby-row' : 'bim-groupby-subrow'}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => toggleExpanded(node.id)}
            aria-expanded={isOpen}
            aria-label={
              isOpen
                ? t('bim.groupby.collapse', { defaultValue: 'Collapse' })
                : t('bim.groupby.expand', { defaultValue: 'Expand' })
            }
            className="p-0.5 mt-0.5 rounded text-content-tertiary hover:text-content-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-oe-blue"
          >
            {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        ) : (
          <span className="w-[18px] shrink-0" />
        )}
        <button
          type="button"
          onClick={() => activate(node)}
          aria-pressed={isActive}
          title={t('bim.groupby.row_title', { defaultValue: 'Show only this group in 3D and select it' })}
          className="flex-1 min-w-0 text-start rounded focus:outline-none focus-visible:ring-1 focus-visible:ring-oe-blue"
        >
          <span className="flex items-center gap-1.5 min-w-0">
            {colour && (
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: colour }} aria-hidden />
            )}
            <span
              className={`text-[11px] truncate ${node.value ? 'text-content-primary font-medium' : 'text-content-tertiary italic'}`}
            >
              {node.value || notSet}
            </span>
            <span className="ms-auto shrink-0 text-[10px] tabular-nums text-content-secondary">
              {node.count.toLocaleString(getNumberLocale())}
            </span>
          </span>
          {quantities.length > 0 && (
            <span className="block text-[10px] tabular-nums text-content-tertiary truncate">{quantities.join(' · ')}</span>
          )}
        </button>
      </div>
    );
  };

  return (
    <section
      className="flex flex-col min-h-0 border-b border-border-light"
      aria-label={t('bim.groupby.title', { defaultValue: 'Group by' })}
      data-testid="bim-groupby-panel"
    >
      <div className="px-3 pt-2.5 pb-2 space-y-1.5 bg-surface-secondary">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('bim.groupby.title', { defaultValue: 'Group by' })}
          </h3>
          <span className="text-[10px] text-content-tertiary tabular-nums">
            {t('bim.groupby.of_filtered', {
              defaultValue: 'Filtered: {{n}}',
              n: elements.length.toLocaleString(getNumberLocale()),
            })}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <label className="min-w-0">
            <span className="sr-only">{t('bim.groupby.level1', { defaultValue: 'Group by' })}</span>
            <select
              className={selectClass}
              value={level1}
              onChange={(e) => {
                setLevel1(e.target.value as GroupKey);
                setActiveId(null);
              }}
              data-testid="bim-groupby-level1"
            >
              {keyOptions}
            </select>
          </label>
          <label className="min-w-0">
            <span className="sr-only">{t('bim.groupby.level2', { defaultValue: 'Then by' })}</span>
            <select
              className={selectClass}
              value={level2}
              onChange={(e) => {
                setLevel2(e.target.value as GroupKey | '');
                setActiveId(null);
              }}
              data-testid="bim-groupby-level2"
            >
              <option value="">{t('bim.groupby.then_by_none', { defaultValue: 'Then by: none' })}</option>
              {keyOptions}
            </select>
          </label>
        </div>
        {!propertiesLoaded && onLoadProperties && (
          <button
            type="button"
            onClick={onLoadProperties}
            disabled={propertiesLoading}
            className="w-full text-start text-[10px] text-oe-blue hover:underline disabled:opacity-60"
            data-testid="bim-groupby-load-props"
          >
            {propertiesLoading
              ? t('bim.groupby.loading_params', { defaultValue: 'Loading all parameters...' })
              : t('bim.groupby.load_params', { defaultValue: 'Load all parameters to group by custom properties' })}
          </button>
        )}
        <div className="flex items-center gap-1 flex-wrap">
          <button
            type="button"
            onClick={() => setColourOn((v) => !v)}
            aria-pressed={colourOn}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium border transition-colors ${
              colourOn
                ? 'bg-oe-blue text-white border-oe-blue'
                : 'border-border-light text-content-secondary hover:bg-surface-tertiary'
            }`}
            data-testid="bim-groupby-colour"
          >
            <Palette size={11} />
            {t('bim.groupby.colour_by_group', { defaultValue: 'Colour by group' })}
          </button>
          <button
            type="button"
            onClick={exportCsv}
            disabled={tree.length === 0}
            className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium border border-border-light text-content-secondary hover:bg-surface-tertiary disabled:opacity-40"
          >
            <Download size={11} />
            CSV
          </button>
          <button
            type="button"
            onClick={() => void exportXlsx()}
            disabled={tree.length === 0}
            className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium border border-border-light text-content-secondary hover:bg-surface-tertiary disabled:opacity-40"
          >
            <FileSpreadsheet size={11} />
            Excel
          </button>
          {activeId && (
            <button
              type="button"
              onClick={() => {
                setActiveId(null);
                onIsolate([]);
                onSelect([]);
              }}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-oe-blue hover:bg-oe-blue/10"
            >
              <Eye size={11} />
              {t('bim.groupby.show_all', { defaultValue: 'Show all' })}
            </button>
          )}
        </div>
      </div>

      <div className="overflow-y-auto max-h-[45vh] divide-y divide-border-light/50" role="list">
        {isLoading ? (
          <p className="px-3 py-4 text-[11px] text-content-tertiary text-center" role="status">
            {t('bim.groupby.loading', { defaultValue: 'Loading elements...' })}
          </p>
        ) : tree.length === 0 ? (
          <p className="px-3 py-4 text-[11px] text-content-tertiary text-center" data-testid="bim-groupby-empty">
            {t('bim.groupby.empty', { defaultValue: 'No elements match the filters. Clear a filter to see groups.' })}
          </p>
        ) : (
          tree.map((node, i) => (
            <div role="listitem" key={node.id}>
              {renderRow(node, 0, colourForIndex(i), node.children.length > 0)}
              {expanded.has(node.id) && node.children.map((c) => renderRow(c, 1, null, false))}
            </div>
          ))
        )}
      </div>

      {tree.length > 0 && (
        <div className="px-3 py-1.5 flex items-center justify-between gap-2 text-[10px] bg-surface-secondary border-t border-border-light">
          <span className="font-semibold text-content-secondary">
            {t('bim.groupby.total', { defaultValue: 'Total' })} · {totals.count.toLocaleString(getNumberLocale())}
          </span>
          <span className="tabular-nums text-content-tertiary truncate">{qtyText(totals).join(' · ')}</span>
        </div>
      )}
      {tree.length > 0 && (
        <p className="px-3 pb-2 pt-1 text-[10px] text-content-quaternary flex items-center gap-1">
          <MousePointerClick size={10} />
          {t('bim.groupby.hint', { defaultValue: 'Click a group to show it alone in 3D. Click again to show all.' })}
        </p>
      )}
    </section>
  );
}
