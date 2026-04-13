/**
 * CustomColumnsDialog — Manage user-defined columns in a BOQ.
 *
 * Lets the user add/remove arbitrary columns (text, number, date, select)
 * that show up in the BOQ grid alongside the standard ones. Useful for
 * supplier names, internal notes, procurement-related fields, etc.
 *
 * Backend stores the column definitions in `boq.metadata_.custom_columns`,
 * and per-position values in `position.metadata_.custom_fields`. Values
 * are preserved when a column is deleted (only the definition is removed).
 *
 * Design choices:
 *
 * - **Presets**: real users don't think "I need a Supplier column" — they
 *   think "I need procurement tracking". One-click presets create groups of
 *   related columns (Procurement, Quality, Sustainability, Notes).
 *
 * - **Fill rate**: each existing column shows "X of Y positions filled" so
 *   the user can spot empty/dead columns at a glance.
 *
 * - **Reserved-name guard**: same list as backend prevents the user from
 *   shadowing built-in fields like `unit`, `quantity`, etc.
 *
 * - **Type-aware editor**: select columns require options up-front; the
 *   form hides irrelevant inputs.
 */

import { useMemo, useState, useCallback, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  X, Plus, Trash2, Columns3,
  Type, Hash, Calendar, List,
  AlertCircle, Package, FileText as NotesIcon,
  ShieldCheck, Leaf, Check, Building2, FileCheck, Boxes,
} from 'lucide-react';
import { Button, Badge, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi, type CustomColumnDef, type Position } from './api';
import { getErrorMessage } from '@/shared/lib/api';

interface CustomColumnsDialogProps {
  open: boolean;
  onClose: () => void;
  boqId: string;
  /** Positions used to compute fill-rate stats per column. Optional — if not
   *  provided, fill rates are not shown. */
  positions?: Position[];
}

const COLUMN_TYPE_ICONS: Record<CustomColumnDef['column_type'], typeof Type> = {
  text: Type,
  number: Hash,
  date: Calendar,
  select: List,
};

/* ── Presets ───────────────────────────────────────────────────────────
 *
 * Each preset is a curated set of columns that solves a single workflow
 * (procurement, quality, sustainability, notes). Adding a preset creates
 * all its columns sequentially; existing columns with the same name are
 * skipped silently so the user can re-apply a preset safely.
 */
interface ColumnPreset {
  id: string;
  name: string;
  description: string;
  icon: typeof Package;
  iconClass: string;
  columns: CustomColumnDef[];
}

const PRESETS: ColumnPreset[] = [
  {
    id: 'procurement',
    name: 'Procurement',
    description: 'Supplier, lead time, PO number, status — for purchasing tracking',
    icon: Package,
    iconClass: 'text-violet-600 bg-violet-500/10',
    columns: [
      { name: 'supplier', display_name: 'Supplier', column_type: 'text' },
      { name: 'lead_time_days', display_name: 'Lead Time (days)', column_type: 'number' },
      { name: 'po_number', display_name: 'PO Number', column_type: 'text' },
      {
        name: 'po_status',
        display_name: 'PO Status',
        column_type: 'select',
        options: ['Quoted', 'Ordered', 'In Transit', 'Delivered', 'Cancelled'],
      },
    ],
  },
  {
    id: 'notes',
    name: 'Notes',
    description: 'Internal note + reference — quick context per position',
    icon: NotesIcon,
    iconClass: 'text-blue-600 bg-blue-500/10',
    columns: [
      { name: 'internal_note', display_name: 'Internal Note', column_type: 'text' },
      { name: 'reference', display_name: 'Reference', column_type: 'text' },
    ],
  },
  {
    id: 'quality',
    name: 'Quality Control',
    description: 'Inspection status, inspector and date — for QA workflow',
    icon: ShieldCheck,
    iconClass: 'text-emerald-600 bg-emerald-500/10',
    columns: [
      {
        name: 'qc_status',
        display_name: 'QC Status',
        column_type: 'select',
        options: ['Pending', 'Passed', 'Failed', 'Rework', 'Waived'],
      },
      { name: 'inspector', display_name: 'Inspector', column_type: 'text' },
      { name: 'inspection_date', display_name: 'Inspection Date', column_type: 'date' },
    ],
  },
  {
    id: 'sustainability',
    name: 'Sustainability',
    description: 'CO₂ footprint, EPD reference and material source',
    icon: Leaf,
    iconClass: 'text-green-600 bg-green-500/10',
    columns: [
      { name: 'co2_kg_per_unit', display_name: 'CO₂ kg/unit', column_type: 'number' },
      { name: 'epd_reference', display_name: 'EPD Reference', column_type: 'text' },
      { name: 'material_source', display_name: 'Material Source', column_type: 'text' },
    ],
  },

  /* ── Professional presets matching established German/Austrian tools ─ */

  {
    id: 'gaeb_ava',
    name: 'GAEB / AVA Style',
    description:
      'Splits unit rate into Lohn / Material / Geräte / Sonstiges + risk markup — matches GAEB X83/X84 standard',
    icon: FileCheck,
    iconClass: 'text-rose-600 bg-rose-500/10',
    columns: [
      { name: 'kg_bezug', display_name: 'KG-Bezug (DIN 276)', column_type: 'text' },
      { name: 'lohn_ep', display_name: 'Lohn-EP', column_type: 'number' },
      { name: 'material_ep', display_name: 'Material-EP', column_type: 'number' },
      { name: 'geraete_ep', display_name: 'Geräte-EP', column_type: 'number' },
      { name: 'sonstiges_ep', display_name: 'Sonstiges-EP', column_type: 'number' },
      { name: 'wagnis_pct', display_name: 'Wagnis %', column_type: 'number' },
    ],
  },
  {
    id: 'oenorm_brz',
    name: 'ÖNORM / BRZ Style',
    description:
      'LV position code, keyword, labor share and supplier — matches Austrian ÖNORM B 2061 / A 2063 used in BRZ',
    icon: Building2,
    iconClass: 'text-orange-600 bg-orange-500/10',
    columns: [
      { name: 'lv_position', display_name: 'LV-Position', column_type: 'text' },
      { name: 'stichwort', display_name: 'Stichwort', column_type: 'text' },
      { name: 'lohn_anteil_pct', display_name: 'Lohn-Anteil %', column_type: 'number' },
      { name: 'aufschlag_pct', display_name: 'Aufschlag %', column_type: 'number' },
      { name: 'lieferant', display_name: 'Lieferant', column_type: 'text' },
    ],
  },
  {
    id: 'bim',
    name: 'BIM Integration',
    description:
      'IFC GUID, element ID, storey and lifecycle phase — for linking BoQ rows to BIM models',
    icon: Boxes,
    iconClass: 'text-cyan-600 bg-cyan-500/10',
    columns: [
      { name: 'ifc_guid', display_name: 'IFC GUID', column_type: 'text' },
      { name: 'element_id', display_name: 'Element ID', column_type: 'text' },
      { name: 'storey', display_name: 'Storey/Level', column_type: 'text' },
      {
        name: 'phase',
        display_name: 'Phase',
        column_type: 'select',
        options: ['Existing', 'Demolition', 'New Construction', 'Temporary'],
      },
    ],
  },
];

/* ── Helpers ───────────────────────────────────────────────────────────── */

const RESERVED_NAMES = new Set([
  'ordinal', 'description', 'unit', 'quantity', 'unit_rate',
  'total', 'id', 'parent_id', 'classification', 'sort_order',
  'metadata', 'created_at', 'updated_at',
]);

function normalizeColumnName(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_]/g, '');
}

/** Count how many positions have a non-empty value for a given column name. */
function fillRateFor(positions: Position[] | undefined, columnName: string): { filled: number; total: number } {
  if (!positions || positions.length === 0) return { filled: 0, total: 0 };
  // Skip section rows when computing fill rate — sections never carry custom values.
  const dataRows = positions.filter((p) => p.unit !== '');
  let filled = 0;
  for (const p of dataRows) {
    const meta = (p.metadata as Record<string, unknown> | undefined) ?? {};
    const cf = (meta.custom_fields as Record<string, unknown> | undefined) ?? {};
    const v = cf[columnName];
    if (v != null && v !== '') filled++;
  }
  return { filled, total: dataRows.length };
}

/* ── Component ────────────────────────────────────────────────────────── */

export function CustomColumnsDialog({
  open,
  onClose,
  boqId,
  positions,
}: CustomColumnsDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  // ── State for the manual "Add column" form ───────────────────────────
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<CustomColumnDef['column_type']>('text');
  const [newOptions, setNewOptions] = useState('');
  const [showCustomForm, setShowCustomForm] = useState(false);

  const { data: columns = [], isLoading } = useQuery({
    queryKey: ['boq-custom-columns', boqId],
    queryFn: () => boqApi.listCustomColumns(boqId),
    enabled: open,
  });

  const existingNames = useMemo(() => new Set(columns.map((c) => c.name)), [columns]);

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['boq-custom-columns', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-with-positions', boqId] });
  }, [queryClient, boqId]);

  const addMut = useMutation({
    mutationFn: (data: CustomColumnDef) => boqApi.addCustomColumn(boqId, data),
    onSuccess: () => {
      invalidateAll();
      setNewName('');
      setNewType('text');
      setNewOptions('');
      setShowCustomForm(false);
      addToast({
        type: 'success',
        title: t('boq.column_added', { defaultValue: 'Column added' }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.column_add_failed', { defaultValue: 'Could not add column' }),
        message: getErrorMessage(err),
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (columnName: string) => boqApi.deleteCustomColumn(boqId, columnName),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('boq.column_removed', { defaultValue: 'Column removed' }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.column_delete_failed', { defaultValue: 'Could not remove column' }),
        message: getErrorMessage(err),
      });
    },
  });

  /* Apply a preset: add each column that doesn't already exist. We do this
   * sequentially to give the backend's per-call uniqueness check a chance
   * to flag any race condition (and to keep error toasts attributable). */
  const applyPreset = useCallback(
    async (preset: ColumnPreset) => {
      const toAdd = preset.columns.filter((c) => !existingNames.has(c.name));
      if (toAdd.length === 0) {
        addToast({
          type: 'info',
          title: t('boq.preset_already_applied', {
            defaultValue: 'All columns from this preset already exist',
          }),
        });
        return;
      }
      let added = 0;
      for (const col of toAdd) {
        try {
          await boqApi.addCustomColumn(boqId, col);
          added++;
        } catch (err) {
          addToast({
            type: 'error',
            title: t('boq.preset_partial', {
              defaultValue: 'Preset partially applied',
            }),
            message: getErrorMessage(err),
          });
          break;
        }
      }
      if (added > 0) {
        invalidateAll();
        addToast({
          type: 'success',
          title: t('boq.preset_applied', {
            defaultValue: '{{count}} columns added from "{{name}}" preset',
            count: added,
            name: preset.name,
          }),
        });
      }
    },
    [boqId, existingNames, invalidateAll, addToast, t],
  );

  /* Manual add form submit */
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = newName.trim();
    if (!trimmed) return;

    const normalizedName = normalizeColumnName(trimmed);
    if (!normalizedName || /^\d/.test(normalizedName)) {
      addToast({
        type: 'error',
        title: t('boq.column_name_invalid', { defaultValue: 'Column name is invalid' }),
        message: t('boq.column_name_invalid_hint', {
          defaultValue: 'Use letters, numbers and spaces. Must start with a letter.',
        }),
      });
      return;
    }
    if (RESERVED_NAMES.has(normalizedName)) {
      addToast({
        type: 'error',
        title: t('boq.column_name_reserved', {
          defaultValue: '"{{name}}" is a reserved column name',
          name: normalizedName,
        }),
      });
      return;
    }
    if (existingNames.has(normalizedName)) {
      addToast({
        type: 'error',
        title: t('boq.column_name_duplicate', {
          defaultValue: 'A column named "{{name}}" already exists',
          name: normalizedName,
        }),
      });
      return;
    }

    const payload: CustomColumnDef = {
      name: normalizedName,
      display_name: trimmed,
      column_type: newType,
    };
    if (newType === 'select') {
      const opts = newOptions
        .split(/[,\n]/)
        .map((o) => o.trim())
        .filter(Boolean);
      if (opts.length === 0) {
        addToast({
          type: 'error',
          title: t('boq.column_select_needs_options', {
            defaultValue: 'Select column needs at least one option',
          }),
        });
        return;
      }
      payload.options = opts;
    }
    addMut.mutate(payload);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative w-full max-w-3xl mx-4 max-h-[90vh] rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 shrink-0 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle">
              <Columns3 size={20} className="text-oe-blue" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('boq.custom_columns', { defaultValue: 'Custom Columns' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('boq.custom_columns_subtitle', {
                  defaultValue: 'Add your own fields — supplier, notes, procurement info…',
                })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto px-6 py-5 flex-1 space-y-6">
          {/* ── Existing columns ─────────────────────────────────────── */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('boq.existing_columns', { defaultValue: 'Existing custom columns' })}
              </h3>
              {columns.length > 0 && (
                <span className="text-2xs text-content-tertiary tabular-nums">
                  {columns.length} {t('boq.columns_count', { defaultValue: 'columns' })}
                </span>
              )}
            </div>
            {isLoading ? (
              <p className="text-sm text-content-tertiary py-3">
                {t('common.loading', { defaultValue: 'Loading…' })}
              </p>
            ) : columns.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg border border-dashed border-border-light px-4 py-5 text-sm text-content-tertiary">
                <AlertCircle size={16} />
                {t('boq.no_custom_columns', {
                  defaultValue: 'No custom columns yet. Pick a preset below or add your own.',
                })}
              </div>
            ) : (
              <div className="rounded-lg border border-border-light divide-y divide-border-light">
                {columns.map((col) => {
                  const Icon = COLUMN_TYPE_ICONS[col.column_type] ?? Type;
                  const fr = fillRateFor(positions, col.name);
                  const fillPct = fr.total > 0 ? Math.round((fr.filled / fr.total) * 100) : 0;
                  return (
                    <div
                      key={col.name}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-surface-secondary/50 transition-colors"
                    >
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-secondary text-content-tertiary shrink-0">
                        <Icon size={15} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-content-primary truncate">
                            {col.display_name}
                          </p>
                          <Badge variant="neutral" size="sm">
                            {col.column_type}
                          </Badge>
                          {col.column_type === 'select' && col.options && col.options.length > 0 && (
                            <span className="text-2xs text-content-tertiary">
                              {col.options.length} {t('boq.options', { defaultValue: 'options' })}
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-2xs text-content-tertiary">
                          <code className="font-mono">{col.name}</code>
                          {fr.total > 0 && (
                            <>
                              <span>·</span>
                              <span className="tabular-nums">
                                {fr.filled}/{fr.total} {t('boq.filled', { defaultValue: 'filled' })}
                              </span>
                              <div className="h-1 w-16 rounded-full bg-surface-secondary overflow-hidden">
                                <div
                                  className={`h-full ${fillPct >= 50 ? 'bg-emerald-500' : fillPct >= 10 ? 'bg-amber-500' : 'bg-content-quaternary'}`}
                                  style={{ width: `${fillPct}%` }}
                                />
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                      <button
                        onClick={async () => {
                          const ok = await confirm({
                            title: t('boq.column_delete_confirm_title', { defaultValue: 'Remove column?' }),
                            message: t('boq.column_delete_confirm', {
                              defaultValue:
                                'Remove the "{{name}}" column? Existing values in positions are preserved but no longer shown.',
                              name: col.display_name,
                            }),
                          });
                          if (ok) deleteMut.mutate(col.name);
                        }}
                        disabled={deleteMut.isPending}
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-colors shrink-0"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* ── Presets ─────────────────────────────────────────────── */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('boq.column_presets', { defaultValue: 'Quick start with a preset' })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {PRESETS.map((preset) => {
                const Icon = preset.icon;
                const allApplied = preset.columns.every((c) => existingNames.has(c.name));
                const someApplied = preset.columns.some((c) => existingNames.has(c.name));
                return (
                  <button
                    key={preset.id}
                    onClick={() => applyPreset(preset)}
                    disabled={allApplied || addMut.isPending}
                    className="flex items-start gap-3 rounded-lg border border-border-light bg-surface-primary p-3 text-left transition-all hover:border-oe-blue/40 hover:bg-oe-blue-subtle/30 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <div
                      className={`flex h-9 w-9 items-center justify-center rounded-lg shrink-0 ${preset.iconClass}`}
                    >
                      <Icon size={16} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-semibold text-content-primary">{preset.name}</p>
                        {allApplied && (
                          <span className="inline-flex items-center gap-0.5 text-2xs font-medium text-emerald-600">
                            <Check size={11} />
                            {t('boq.applied', { defaultValue: 'Applied' })}
                          </span>
                        )}
                        {someApplied && !allApplied && (
                          <span className="text-2xs font-medium text-amber-600">
                            {t('boq.partial', { defaultValue: 'Partial' })}
                          </span>
                        )}
                      </div>
                      <p className="text-2xs text-content-tertiary mt-0.5 line-clamp-2">
                        {preset.description}
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {preset.columns.map((c) => (
                          <span
                            key={c.name}
                            className={`inline-block rounded px-1.5 py-0.5 text-2xs ${existingNames.has(c.name) ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : 'bg-surface-secondary text-content-secondary'}`}
                          >
                            {c.display_name}
                          </span>
                        ))}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {/* ── Manual add ──────────────────────────────────────────── */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('boq.add_custom_column', { defaultValue: 'Or add a custom one' })}
              </h3>
              {!showCustomForm && (
                <button
                  type="button"
                  onClick={() => setShowCustomForm(true)}
                  className="text-xs font-medium text-oe-blue hover:underline"
                >
                  {t('boq.show_form', { defaultValue: 'Show form' })}
                </button>
              )}
            </div>
            {showCustomForm && (
              <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-4">
                <form onSubmit={handleSubmit} className="space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label
                        htmlFor="column-name"
                        className="block text-xs font-medium text-content-secondary mb-1.5"
                      >
                        {t('boq.column_name', { defaultValue: 'Column name' })}
                      </label>
                      <input
                        id="column-name"
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder={t('boq.column_name_placeholder', {
                          defaultValue: 'e.g. Supplier, Notes, PO Number',
                        })}
                        className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all"
                        autoFocus
                      />
                      {newName && (
                        <p className="mt-1 text-2xs text-content-tertiary">
                          {t('boq.internal_name', { defaultValue: 'Internal name' })}:{' '}
                          <code className="font-mono">{normalizeColumnName(newName)}</code>
                        </p>
                      )}
                    </div>
                    <div>
                      <label
                        htmlFor="column-type"
                        className="block text-xs font-medium text-content-secondary mb-1.5"
                      >
                        {t('boq.column_type', { defaultValue: 'Type' })}
                      </label>
                      <select
                        id="column-type"
                        value={newType}
                        onChange={(e) => setNewType(e.target.value as CustomColumnDef['column_type'])}
                        className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all"
                      >
                        <option value="text">{t('boq.column_type_text', { defaultValue: 'Text' })}</option>
                        <option value="number">{t('boq.column_type_number', { defaultValue: 'Number' })}</option>
                        <option value="date">{t('boq.column_type_date', { defaultValue: 'Date' })}</option>
                        <option value="select">{t('boq.column_type_select', { defaultValue: 'Select (dropdown)' })}</option>
                      </select>
                    </div>
                  </div>

                  {newType === 'select' && (
                    <div>
                      <label
                        htmlFor="column-options"
                        className="block text-xs font-medium text-content-secondary mb-1.5"
                      >
                        {t('boq.column_options', { defaultValue: 'Options (comma or newline separated)' })}
                      </label>
                      <textarea
                        id="column-options"
                        value={newOptions}
                        onChange={(e) => setNewOptions(e.target.value)}
                        placeholder="Approved, Pending, Rejected"
                        rows={2}
                        className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all resize-none"
                      />
                    </div>
                  )}

                  <div className="flex justify-end gap-2 pt-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setShowCustomForm(false);
                        setNewName('');
                        setNewOptions('');
                      }}
                    >
                      {t('common.cancel', { defaultValue: 'Cancel' })}
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      size="sm"
                      disabled={!newName.trim() || addMut.isPending}
                    >
                      <Plus size={14} className="mr-1.5" />
                      {t('boq.add_column_btn', { defaultValue: 'Add column' })}
                    </Button>
                  </div>
                </form>
              </div>
            )}
          </section>
        </div>

        {/* Footer */}
        <div className="border-t border-border-light px-6 py-3 shrink-0">
          <p className="text-xs text-content-tertiary">
            {t('boq.custom_columns_hint', {
              defaultValue:
                'Custom columns appear in the BOQ grid before the actions column. Values are stored per position and exported with the BOQ. Removing a column hides it but preserves the underlying data.',
            })}
          </p>
        </div>
      </div>
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
