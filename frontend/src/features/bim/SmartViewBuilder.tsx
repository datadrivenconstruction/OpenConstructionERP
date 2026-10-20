// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SmartViewBuilder — visual rule-tree editor for the BIM module.
 *
 * Replaces the legacy IFC-biased "filter chips + property search" UI with a
 * canonical-format-aware rule builder that works for ANY CAD source
 * (RVT / IFC / DWG / PDF photo-takeoff).  Built around three pickers
 * (Property → Operator → Value) plus AND/OR groups that can nest.
 *
 * Backend wires:
 *   GET  /v1/bim_hub/smart-views/properties?model_id=<id>
 *        — Property Catalog grouped by Identity / Geometry / Quantities /
 *          Properties with sample-value previews + source-format badges.
 *   POST /v1/bim_hub/smart-views/preview
 *        — Live count + sample ids for matching elements (drives the
 *          "234 match" pill and the 5-card sample preview strip).
 *
 * Sub-components in this file (kept local to avoid an explosion of tiny
 * files — every one of them is < 130 LoC and only the builder is
 * exported):
 *   - PropertyPicker — search-as-you-type, grouped dropdown, source badges
 *   - OperatorPicker — type-aware operator menu with hint tooltips
 *   - ValueInput     — type-aware input (enum dropdown / number / between)
 *   - GroupRenderer  — recursive AND/OR tree node with inline error UX
 *   - SamplePreview  — 3-5 matching elements rendered as cards
 *
 * Areas worth highlighting:
 *   - **Validation**: walked once per tree change → emits a Map<path,
 *     error> that the renderer reads to surface inline error messages
 *     (invalid regex, empty value, MAX_DEPTH, etc.).
 *   - **A11y**: the group/leaf hierarchy is exposed as a WAI-ARIA tree
 *     (``role="tree"`` at the root, ``role="treeitem"`` + ``aria-level``
 *     on every node).
 *   - **Persistence**: starred + recent saved-view ids live in
 *     localStorage via ``useSmartViewShortcuts`` — the chip strip
 *     above the presets shows them with apply / unstar actions.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  AlertCircle,
  ChevronDown,
  Clock,
  Info,
  Plus,
  Save,
  Search,
  Star,
  Trash2,
  X,
  Zap,
} from 'lucide-react';
import {
  fetchBIMElementsByIds,
  fetchSmartViewProperties,
  listElementGroups,
  previewSmartView,
  type BIMElementGroup,
  type SmartViewGroup,
  type SmartViewLeaf,
  type SmartViewOp,
  type SmartViewProperty,
  type SmartViewPropertyCatalog,
} from './api';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import SaveSmartViewModal from './SaveSmartViewModal';
import { useSmartViewShortcuts } from './useSmartViewShortcuts';

/* ── Helpers ────────────────────────────────────────────────────────────── */

/** Tree-depth + leaf-count guards mirror the backend (smart_views.py).
 *  Surfaced in the UI so users see the limit before posting. */
const MAX_DEPTH = 6;
const MAX_LEAVES = 100;

/** All operators in the engine, grouped by which data_type they apply to. */
const STRING_OPS: SmartViewOp[] = [
  '=',
  '!=',
  'contains',
  'starts_with',
  'ends_with',
  'regex',
  'in',
  'not_in',
  'is_empty',
  'is_not_empty',
];
const NUMERIC_OPS: SmartViewOp[] = [
  '=',
  '!=',
  '>',
  '<',
  '>=',
  '<=',
  'between',
  'in',
  'not_in',
  'is_empty',
  'is_not_empty',
];

/** Human-readable label for each operator — keyed by op symbol. */
function opLabel(op: SmartViewOp): string {
  const table: Record<SmartViewOp, string> = {
    '=': 'equals',
    '!=': 'not equals',
    contains: 'contains',
    starts_with: 'starts with',
    ends_with: 'ends with',
    regex: 'matches regex',
    '>': 'greater than',
    '<': 'less than',
    '>=': 'at least',
    '<=': 'at most',
    between: 'between',
    in: 'is any of',
    not_in: 'is none of',
    is_empty: 'is empty',
    is_not_empty: 'is set',
  };
  return table[op];
}

/** One-liner hint shown on the (?) tooltip next to the operator
 *  dropdown.  Empty string means "no hint needed". */
function opHint(op: SmartViewOp): string {
  const table: Partial<Record<SmartViewOp, string>> = {
    regex: 'JavaScript-style RegExp. Example: ^IfcWall.* matches every type starting with "IfcWall".',
    between: 'Inclusive on both ends. Example: 5 … 20 matches 5, 12, 20.',
    in: 'Matches if the element value equals ANY of the listed values.',
    not_in: 'Matches if the element value equals NONE of the listed values.',
    is_empty: 'Matches elements where this property is missing, null or "".',
    is_not_empty: 'Matches elements where this property has any value.',
    contains: 'Case-insensitive substring search.',
    starts_with: 'Case-insensitive prefix match.',
    ends_with: 'Case-insensitive suffix match.',
  };
  return table[op] ?? '';
}

function isGroup(node: SmartViewLeaf | SmartViewGroup): node is SmartViewGroup {
  return (
    typeof (node as SmartViewGroup).op === 'string' &&
    ((node as SmartViewGroup).op === 'AND' || (node as SmartViewGroup).op === 'OR')
  );
}

/** Build a deep clone of the tree so we can mutate immutably. */
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

/* ── Validation ─────────────────────────────────────────────────────────── */

/** A tree-wide validation report.  Keys are the dot-joined path of the
 *  offending node (e.g. ``"0.1.2"`` for ``group.rules[0].rules[1].rules[2]``);
 *  values are the localised error message.  Empty map ⇒ tree is valid. */
type NodeErrors = Map<string, string>;

interface ValidationReport {
  errors: NodeErrors;
  treeErrors: string[];
  leafCount: number;
  maxDepth: number;
}

/** Walk the rule tree once and collect all problems.
 *
 *  Per-leaf checks:
 *    - field is non-empty
 *    - value is non-empty for ops that need one (everything except
 *      ``is_empty`` / ``is_not_empty``)
 *    - ``regex`` op compiles
 *    - ``between`` value is a tuple of two finite numbers, min <= max
 *    - ``in`` / ``not_in`` value is a non-empty array
 *
 *  Tree-level checks:
 *    - leaf count <= MAX_LEAVES
 *    - depth     <= MAX_DEPTH
 *    - root group has at least one rule (warning, not error) */
function validateTree(root: SmartViewGroup): ValidationReport {
  const errors: NodeErrors = new Map();
  const treeErrors: string[] = [];
  let leafCount = 0;
  let maxDepth = 0;

  const walk = (
    node: SmartViewLeaf | SmartViewGroup,
    path: number[],
    depth: number,
  ): void => {
    maxDepth = Math.max(maxDepth, depth);
    if (isGroup(node)) {
      if (depth > MAX_DEPTH) {
        errors.set(path.join('.'), `Maximum nesting depth (${MAX_DEPTH}) exceeded`);
        return;
      }
      node.rules.forEach((child, idx) => walk(child, [...path, idx], depth + 1));
      return;
    }
    leafCount += 1;
    const key = path.join('.');
    if (!node.field || !node.field.trim()) {
      errors.set(key, 'Property is required');
      return;
    }
    const needsValue = node.op !== 'is_empty' && node.op !== 'is_not_empty';
    if (!needsValue) return;

    if (node.op === 'regex') {
      const v = (node.value ?? '') as string;
      if (!v) {
        errors.set(key, 'Regex pattern is required');
        return;
      }
      try {
        // eslint-disable-next-line no-new
        new RegExp(v);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        errors.set(key, `Invalid regex: ${msg}`);
      }
      return;
    }

    if (node.op === 'between') {
      const tuple = Array.isArray(node.value) ? (node.value as unknown[]) : [];
      if (tuple.length !== 2) {
        errors.set(key, 'Between needs a min and a max value');
        return;
      }
      const [lo, hi] = tuple as [unknown, unknown];
      if (
        typeof lo !== 'number' ||
        typeof hi !== 'number' ||
        Number.isNaN(lo) ||
        Number.isNaN(hi)
      ) {
        errors.set(key, 'Between values must be numbers');
        return;
      }
      if (lo > hi) {
        errors.set(key, `Min (${lo}) must be ≤ max (${hi})`);
      }
      return;
    }

    if (node.op === 'in' || node.op === 'not_in') {
      const arr = Array.isArray(node.value) ? (node.value as unknown[]) : [];
      if (arr.length === 0) {
        errors.set(key, 'Add at least one value');
      }
      return;
    }

    if (
      node.value === undefined ||
      node.value === null ||
      (typeof node.value === 'string' && node.value.trim() === '')
    ) {
      errors.set(key, 'Value is required');
    }
  };

  walk(root, [], 0);

  if (leafCount > MAX_LEAVES) {
    treeErrors.push(`Rule count (${leafCount}) exceeds the limit of ${MAX_LEAVES}`);
  }
  if (maxDepth > MAX_DEPTH) {
    treeErrors.push(`Group nesting (${maxDepth}) exceeds the limit of ${MAX_DEPTH}`);
  }
  return { errors, treeErrors, leafCount, maxDepth };
}

/* ── Quick presets — pre-built rule recipes ─────────────────────────────── */

interface Preset {
  id: string;
  label: string;
  build: () => SmartViewGroup;
}

const PRESETS: Preset[] = [
  {
    id: 'walls',
    label: 'Walls only',
    build: () => ({
      op: 'OR',
      rules: [
        { field: 'element_type', op: 'in', value: ['IfcWall', 'Walls', 'wall'] },
        { field: 'category', op: '=', value: 'wall' },
      ],
    }),
  },
  {
    id: 'doors',
    label: 'Doors only',
    build: () => ({
      op: 'OR',
      rules: [
        { field: 'element_type', op: 'in', value: ['IfcDoor', 'Doors', 'door'] },
        { field: 'category', op: '=', value: 'door' },
      ],
    }),
  },
  {
    id: 'concrete',
    label: 'Concrete elements',
    build: () => ({
      op: 'AND',
      rules: [
        { field: 'properties.material', op: 'contains', value: 'concrete' },
      ],
    }),
  },
  {
    id: 'din330',
    label: 'DIN 276: Outer walls (330)',
    build: () => ({
      op: 'AND',
      rules: [{ field: 'identity.din276', op: '=', value: '330' }],
    }),
  },
  {
    id: 'tall',
    label: 'Tall elements (h > 3 m)',
    build: () => ({
      op: 'AND',
      rules: [
        { field: 'geometry.height_m', op: '>', value: 3 },
      ],
    }),
  },
  {
    id: 'no_material',
    label: 'Missing material',
    build: () => ({
      op: 'AND',
      rules: [{ field: 'properties.material', op: 'is_empty' }],
    }),
  },
  {
    id: 'above_level_2',
    label: 'Above level 2',
    build: () => ({
      op: 'OR',
      rules: [
        { field: 'storey', op: 'regex', value: '^(Level\\s?0?[3-9]|Level\\s?[1-9]\\d+)' },
        { field: 'storey', op: 'in', value: ['Level 3', 'Level 4', 'Level 5'] },
      ],
    }),
  },
  {
    id: 'unclassified',
    label: 'Unclassified',
    build: () => ({
      op: 'AND',
      rules: [
        { field: 'identity.din276', op: 'is_empty' },
      ],
    }),
  },
];

/* ── Property Picker ────────────────────────────────────────────────────── */

interface PropertyPickerProps {
  catalog: SmartViewPropertyCatalog | null | undefined;
  value: string;
  onChange: (field: string, entry: SmartViewProperty | undefined) => void;
  disabled?: boolean;
}

function PropertyPicker({ catalog, value, onChange, disabled }: PropertyPickerProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const entries = catalog?.entries ?? [];
  const selected = entries.find((e) => e.field === value);

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? entries.filter(
          (e) =>
            e.field.toLowerCase().includes(q) ||
            e.label.toLowerCase().includes(q) ||
            e.sample_values.some((s) => s.toLowerCase().includes(q)),
        )
      : entries;
    const out: Record<string, SmartViewProperty[]> = {
      identity: [],
      geometry: [],
      quantities: [],
      properties: [],
    };
    for (const e of filtered) out[e.group]?.push(e);
    return out;
  }, [entries, query]);

  const totalShown = useMemo(
    () => Object.values(grouped).reduce((sum, list) => sum + (list?.length ?? 0), 0),
    [grouped],
  );

  const groupTitles: Record<string, string> = {
    identity: t('bim.smartview.group_identity', { defaultValue: 'Identity' }),
    geometry: t('bim.smartview.group_geometry', { defaultValue: 'Geometry' }),
    quantities: t('bim.smartview.group_quantities', { defaultValue: 'Quantities' }),
    properties: t('bim.smartview.group_properties', { defaultValue: 'Properties' }),
  };

  return (
    <div className="relative inline-block">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('bim.smartview.pick_property', {
          defaultValue: 'Pick a property…',
        })}
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded border text-[11px] ${
          disabled
            ? 'border-border-light bg-surface-tertiary text-content-quaternary'
            : 'border-border-light bg-surface-secondary text-content-primary hover:bg-surface-tertiary'
        }`}
        title={selected?.field}
      >
        {selected ? (
          <>
            <span className="text-[9px] font-bold uppercase tracking-wider text-content-tertiary">
              {selected.group.slice(0, 3)}
            </span>
            <span className="font-medium">{selected.label}</span>
            {selected.source_formats[0] && (
              <span className="text-[8px] font-bold uppercase tracking-wider px-1 rounded bg-oe-blue/10 text-oe-blue">
                {selected.source_formats[0]}
              </span>
            )}
          </>
        ) : (
          <span className="text-content-tertiary">
            {t('bim.smartview.pick_property', { defaultValue: 'Pick a property…' })}
          </span>
        )}
        <ChevronDown size={10} className="text-content-quaternary" />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute z-30 mt-1 w-[340px] max-h-[440px] overflow-auto rounded-md border border-border-light bg-surface-primary shadow-lg"
          onMouseLeave={() => setOpen(false)}
        >
          <div className="sticky top-0 bg-surface-primary border-b border-border-light p-2">
            <div className="relative">
              <Search
                size={12}
                className="absolute start-2 top-1/2 -translate-y-1/2 text-content-quaternary"
              />
              <input
                autoFocus
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('bim.smartview.search_properties', {
                  defaultValue: 'Search properties…',
                })}
                className="w-full ps-7 pe-2 py-1 text-[11px] rounded border border-border-light bg-surface-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              />
            </div>
            <div className="flex items-center justify-between mt-1 text-[9px] text-content-tertiary uppercase tracking-wider">
              <span>
                {t('bim.smartview.props_shown', {
                  defaultValue: '{{n}} of {{total}}',
                  n: totalShown,
                  total: entries.length,
                })}
              </span>
              {catalog?.source_format && (
                <span className="font-bold px-1 rounded bg-oe-blue/10 text-oe-blue">
                  {catalog.source_format}
                </span>
              )}
            </div>
          </div>
          {(['identity', 'geometry', 'quantities', 'properties'] as const).map(
            (g) => {
              const list = grouped[g];
              if (!list || list.length === 0) return null;
              return (
                <div key={g} className="py-1">
                  <div className="sticky top-[60px] z-10 px-2 pt-1 pb-0.5 text-[9px] font-bold uppercase tracking-wider text-content-tertiary bg-surface-primary border-b border-border-light/60">
                    {groupTitles[g]}{' '}
                    <span className="text-content-quaternary normal-case font-normal">
                      ({list.length})
                    </span>
                  </div>
                  {list.map((entry) => (
                    <button
                      key={entry.field}
                      type="button"
                      role="option"
                      aria-selected={value === entry.field}
                      onClick={() => {
                        onChange(entry.field, entry);
                        setOpen(false);
                        setQuery('');
                      }}
                      className={`w-full flex items-center gap-1.5 px-2 py-1 text-[11px] text-start hover:bg-surface-secondary ${
                        value === entry.field
                          ? 'bg-oe-blue/10 text-oe-blue'
                          : 'text-content-primary'
                      }`}
                    >
                      <span className="font-medium truncate flex-1">
                        {entry.label}
                      </span>
                      <span className="text-[9px] text-content-quaternary tabular-nums shrink-0">
                        {entry.distinct_count}
                      </span>
                      {entry.source_formats[0] && (
                        <span className="text-[8px] font-bold uppercase px-1 rounded bg-surface-secondary text-content-tertiary">
                          {entry.source_formats[0]}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              );
            },
          )}
          {entries.length === 0 && (
            <div className="px-3 py-4 text-[11px] text-content-tertiary italic text-center">
              {t('bim.smartview.no_properties', {
                defaultValue: 'No properties discovered for this model yet.',
              })}
            </div>
          )}
          {entries.length > 0 && totalShown === 0 && (
            <div className="px-3 py-4 text-[11px] text-content-tertiary italic text-center">
              {t('bim.smartview.no_match', {
                defaultValue: 'No property matches your search.',
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Operator Picker ────────────────────────────────────────────────────── */

interface OperatorPickerProps {
  dataType: SmartViewProperty['data_type'] | undefined;
  value: SmartViewOp;
  onChange: (op: SmartViewOp) => void;
  disabled?: boolean;
}

function OperatorPicker({ dataType, value, onChange, disabled }: OperatorPickerProps) {
  const { t } = useTranslation();
  const ops = useMemo(() => {
    if (dataType === 'number') return NUMERIC_OPS;
    return STRING_OPS;
  }, [dataType]);
  const hint = opHint(value);
  return (
    <div className="inline-flex items-center gap-1">
      <select
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value as SmartViewOp)}
        aria-label={t('bim.smartview.operator', { defaultValue: 'Operator' })}
        className="px-2 py-1 rounded border border-border-light bg-surface-secondary text-[11px] text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue disabled:opacity-50"
      >
        {ops.map((op) => (
          <option key={op} value={op}>
            {opLabel(op)}
          </option>
        ))}
      </select>
      {hint && (
        <span
          title={hint}
          aria-label={hint}
          className="cursor-help text-content-quaternary hover:text-oe-blue"
        >
          <Info size={11} />
        </span>
      )}
    </div>
  );
}

/* ── Value Input ────────────────────────────────────────────────────────── */

interface ValueInputProps {
  property: SmartViewProperty | undefined;
  op: SmartViewOp;
  value: unknown;
  onChange: (value: unknown) => void;
  invalid?: boolean;
}

function ValueInput({ property, op, value, onChange, invalid }: ValueInputProps) {
  const { t } = useTranslation();

  const baseInputCls =
    `px-1.5 py-1 rounded border bg-surface-secondary text-[11px] focus:outline-none focus:ring-1 ${
      invalid
        ? 'border-rose-400 focus:ring-rose-500'
        : 'border-border-light focus:ring-oe-blue'
    }`;

  // No value needed for empty checks.
  if (op === 'is_empty' || op === 'is_not_empty') {
    return <span className="text-[11px] text-content-quaternary italic">—</span>;
  }

  // between → two numeric inputs.
  if (op === 'between') {
    const tuple = Array.isArray(value) ? value : [];
    return (
      <div className="inline-flex items-center gap-1">
        <input
          type="number"
          value={(tuple[0] as number | undefined) ?? ''}
          onChange={(e) => onChange([Number(e.target.value), tuple[1] ?? 0])}
          aria-label={t('bim.smartview.min', { defaultValue: 'Min' })}
          aria-invalid={invalid || undefined}
          className={`w-16 ${baseInputCls}`}
          placeholder="min"
        />
        <span className="text-[10px] text-content-tertiary">…</span>
        <input
          type="number"
          value={(tuple[1] as number | undefined) ?? ''}
          onChange={(e) => onChange([tuple[0] ?? 0, Number(e.target.value)])}
          aria-label={t('bim.smartview.max', { defaultValue: 'Max' })}
          aria-invalid={invalid || undefined}
          className={`w-16 ${baseInputCls}`}
          placeholder="max"
        />
      </div>
    );
  }

  // in / not_in → comma-separated multi value (with autocomplete from
  // sample_values when the property is an enum).
  if (op === 'in' || op === 'not_in') {
    const arr = Array.isArray(value) ? value : [];
    return (
      <div
        className={`inline-flex flex-wrap items-center gap-1 max-w-[280px] ${
          invalid ? 'ring-1 ring-rose-400 rounded p-0.5' : ''
        }`}
      >
        {arr.map((v, i) => (
          <span
            key={`${String(v)}-${i}`}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-oe-blue/10 text-oe-blue"
          >
            {String(v)}
            <button
              type="button"
              onClick={() => onChange(arr.filter((_, j) => j !== i))}
              className="hover:text-rose-600"
              aria-label={t('common.remove', { defaultValue: 'Remove' })}
            >
              <X size={9} />
            </button>
          </span>
        ))}
        <select
          value=""
          onChange={(e) => {
            const next = e.target.value;
            if (next && !arr.includes(next)) onChange([...arr, next]);
          }}
          className="px-1 py-0.5 rounded border border-border-light bg-surface-secondary text-[11px] focus:outline-none focus:ring-1 focus:ring-oe-blue"
        >
          <option value="">
            {t('bim.smartview.add_value', { defaultValue: '+ add' })}
          </option>
          {(property?.sample_values ?? []).map((sv) => (
            <option key={sv} value={sv}>
              {sv}
            </option>
          ))}
        </select>
      </div>
    );
  }

  // Numeric ops → number input.
  if (
    property?.data_type === 'number' ||
    op === '>' ||
    op === '<' ||
    op === '>=' ||
    op === '<='
  ) {
    return (
      <input
        type="number"
        value={(value as number | string | undefined) ?? ''}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-invalid={invalid || undefined}
        className={`w-24 ${baseInputCls}`}
      />
    );
  }

  // Enum → dropdown with the model's distinct values.
  if (
    property?.data_type === 'enum' &&
    property.sample_values.length > 0 &&
    (op === '=' || op === '!=')
  ) {
    return (
      <select
        value={(value as string | undefined) ?? ''}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid || undefined}
        className={`max-w-[180px] ${baseInputCls}`}
      >
        <option value="">{t('common.select', { defaultValue: 'Select…' })}</option>
        {property.sample_values.map((sv) => (
          <option key={sv} value={sv}>
            {sv}
          </option>
        ))}
      </select>
    );
  }

  // Default — free-text input.
  return (
    <input
      type="text"
      value={(value as string | undefined) ?? ''}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid || undefined}
      className={`w-32 ${baseInputCls}`}
      placeholder={op === 'regex' ? '^foo.*$' : 'value'}
    />
  );
}

/* ── Recursive group renderer ──────────────────────────────────────────── */

interface GroupRendererProps {
  group: SmartViewGroup;
  path: number[];
  catalog: SmartViewPropertyCatalog | null | undefined;
  onChange: (next: SmartViewGroup) => void;
  depth: number;
  errors: NodeErrors;
}

function GroupRenderer({
  group,
  path,
  catalog,
  onChange,
  depth,
  errors,
}: GroupRendererProps) {
  const { t } = useTranslation();
  const propertyByField = useMemo(() => {
    const map = new Map<string, SmartViewProperty>();
    for (const e of catalog?.entries ?? []) map.set(e.field, e);
    return map;
  }, [catalog]);

  const toggleOp = () => {
    const next = clone(group);
    next.op = next.op === 'AND' ? 'OR' : 'AND';
    onChange(next);
  };
  const addLeaf = () => {
    const next = clone(group);
    next.rules.push({ field: 'element_type', op: '=', value: '' });
    onChange(next);
  };
  const addGroup = () => {
    const next = clone(group);
    next.rules.push({ op: 'AND', rules: [] });
    onChange(next);
  };
  const removeChild = (idx: number) => {
    const next = clone(group);
    next.rules.splice(idx, 1);
    onChange(next);
  };
  const updateChild = (idx: number, child: SmartViewLeaf | SmartViewGroup) => {
    const next = clone(group);
    next.rules[idx] = child;
    onChange(next);
  };

  const groupErrorKey = path.join('.');
  const groupError = errors.get(groupErrorKey);

  return (
    <div
      role={depth === 0 ? 'tree' : 'treeitem'}
      aria-level={depth + 1}
      aria-label={t('bim.smartview.group_aria', {
        defaultValue: '{{op}} group with {{n}} rules',
        op: group.op,
        n: group.rules.length,
      })}
      className={`rounded-md border p-2 space-y-1.5 ${
        groupError
          ? 'border-rose-400 bg-rose-50/30 dark:bg-rose-950/10'
          : depth === 0
            ? 'border-border-light bg-surface-primary'
            : 'border-dashed border-border-light bg-surface-secondary/40'
      }`}
    >
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={toggleOp}
          aria-label={t('bim.smartview.toggle_andor', {
            defaultValue: 'Click to switch AND ↔ OR',
          })}
          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
            group.op === 'AND'
              ? 'bg-oe-blue text-white'
              : 'bg-amber-500 text-white'
          }`}
          title={t('bim.smartview.toggle_andor', {
            defaultValue: 'Click to switch AND ↔ OR',
          })}
        >
          {group.op}
        </button>
        <span className="text-[10px] text-content-tertiary">
          {group.rules.length === 0
            ? t('bim.smartview.empty_group', {
                defaultValue: 'No rules yet - add one →',
              })
            : t('bim.smartview.rule_count', {
                defaultValue: '{{n}} rules',
                n: group.rules.length,
              })}
        </span>
        <div className="ms-auto flex items-center gap-1">
          <button
            type="button"
            onClick={addLeaf}
            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] text-content-secondary hover:bg-surface-tertiary"
          >
            <Plus size={9} />
            {t('bim.smartview.add_rule', { defaultValue: 'Rule' })}
          </button>
          {depth < MAX_DEPTH - 1 && (
            <button
              type="button"
              onClick={addGroup}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] text-content-secondary hover:bg-surface-tertiary"
            >
              <Plus size={9} />
              {t('bim.smartview.add_group', { defaultValue: 'Group' })}
            </button>
          )}
        </div>
      </div>
      {groupError && (
        <div className="flex items-center gap-1 text-[10px] text-rose-700 dark:text-rose-300">
          <AlertCircle size={10} />
          <span>{groupError}</span>
        </div>
      )}
      {group.rules.length > 0 && (
        <div role="group" className="space-y-1 ps-2 border-s-2 border-border-light/70">
          {group.rules.map((child, idx) => {
            if (isGroup(child)) {
              return (
                <div key={`g-${idx}`} className="flex items-start gap-1">
                  <div className="flex-1 min-w-0">
                    <GroupRenderer
                      group={child}
                      path={[...path, idx]}
                      catalog={catalog}
                      onChange={(next) => updateChild(idx, next)}
                      depth={depth + 1}
                      errors={errors}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeChild(idx)}
                    className="mt-1 p-0.5 rounded text-content-quaternary hover:text-rose-600"
                    title={t('common.remove', { defaultValue: 'Remove' })}
                    aria-label={t('common.remove', { defaultValue: 'Remove' })}
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              );
            }
            const property = propertyByField.get(child.field);
            const childPath = [...path, idx].join('.');
            const childError = errors.get(childPath);
            return (
              <div
                key={`l-${idx}`}
                role="treeitem"
                aria-level={depth + 2}
                aria-invalid={Boolean(childError) || undefined}
                className="flex flex-col gap-0.5"
              >
                <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
                  <PropertyPicker
                    catalog={catalog}
                    value={child.field}
                    onChange={(field, entry) => {
                      // When the field type changes, reset value to a sane default.
                      const next: SmartViewLeaf = { ...child, field };
                      if (entry?.data_type === 'number') {
                        next.value = 0;
                        if (!NUMERIC_OPS.includes(child.op)) next.op = '=';
                      } else {
                        if (!STRING_OPS.includes(child.op)) next.op = '=';
                        next.value = '';
                      }
                      updateChild(idx, next);
                    }}
                  />
                  <OperatorPicker
                    dataType={property?.data_type}
                    value={child.op}
                    onChange={(op) => updateChild(idx, { ...child, op })}
                  />
                  <ValueInput
                    property={property}
                    op={child.op}
                    value={child.value}
                    onChange={(value) => updateChild(idx, { ...child, value })}
                    invalid={Boolean(childError)}
                  />
                  <button
                    type="button"
                    onClick={() => removeChild(idx)}
                    className="ms-auto p-0.5 rounded text-content-quaternary hover:text-rose-600"
                    title={t('common.remove', { defaultValue: 'Remove' })}
                    aria-label={t('common.remove', { defaultValue: 'Remove' })}
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
                {childError && (
                  <div className="flex items-center gap-1 ps-1 text-[10px] text-rose-700 dark:text-rose-300">
                    <AlertCircle size={10} />
                    <span>{childError}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Sample preview strip ───────────────────────────────────────────────── */

interface SamplePreviewProps {
  modelId: string | null;
  sampleIds: string[];
}

/** Renders 3-5 sample matching elements as little cards so the user can
 *  sanity-check the rule before saving.  Lazy-loads detail rows via
 *  ``fetchBIMElementsByIds`` keyed by the id set. */
function SamplePreview({ modelId, sampleIds }: SamplePreviewProps) {
  const { t } = useTranslation();
  const ids = useMemo(() => sampleIds.slice(0, 5), [sampleIds]);
  const samplesQuery = useQuery({
    queryKey: ['bim-smart-view-samples', modelId, ids],
    enabled: !!modelId && ids.length > 0,
    queryFn: () => fetchBIMElementsByIds(modelId!, ids),
    staleTime: 30 * 1000,
  });
  if (!modelId || ids.length === 0) return null;
  const rows: BIMElementData[] = samplesQuery.data?.items ?? [];
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
        {t('bim.smartview.sample_title', {
          defaultValue: 'Sample matches ({{n}})',
          n: rows.length,
        })}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
        {samplesQuery.isFetching && rows.length === 0
          ? Array.from({ length: ids.length }).map((_, i) => (
              <div
                key={`sk-${i}`}
                className="h-10 rounded border border-border-light bg-surface-secondary/60 animate-pulse"
              />
            ))
          : rows.map((row) => (
              <div
                key={row.id}
                className="rounded border border-border-light bg-surface-secondary px-2 py-1 text-[10px]"
                title={`${row.element_type} • ${row.id}`}
              >
                <div className="font-medium text-content-primary truncate">
                  {row.name || row.element_type}
                </div>
                <div className="flex items-center gap-1 text-content-tertiary">
                  <span className="truncate">{row.element_type}</span>
                  {row.storey && (
                    <span className="text-[8px] uppercase font-bold px-1 rounded bg-surface-tertiary">
                      {row.storey}
                    </span>
                  )}
                </div>
              </div>
            ))}
      </div>
    </div>
  );
}

/* ── Public API ─────────────────────────────────────────────────────────── */

export interface SmartViewBuilderProps {
  modelId: string | null;
  projectId: string | null;
  /** Current rule tree.  Pass an empty AND group to start from scratch. */
  value: SmartViewGroup;
  onChange: (next: SmartViewGroup) => void;
  /** Optional CTA shown next to the live count — e.g. "Save as Smart View".
   *  When omitted, the built-in "Save" button (which opens
   *  ``SaveSmartViewModal``) is rendered instead. */
  renderActions?: (matchedCount: number) => React.ReactNode;
  /** Hide the built-in Save button (when host renders a custom CTA via
   *  ``renderActions`` and doesn't want the duplicate). */
  hideSaveButton?: boolean;
  /** Hide the sample preview strip — used when the host already shows
   *  matched elements elsewhere. */
  hideSamples?: boolean;
}

/**
 * SmartViewBuilder — full visual rule builder.  Renders presets, the
 * group tree (with nesting), a debounced live preview pill, a 5-card
 * sample-match strip, and either a host-supplied CTA or a built-in
 * "Save as Smart View" button that opens ``SaveSmartViewModal``.
 */
export default function SmartViewBuilder({
  modelId,
  projectId,
  value,
  onChange,
  renderActions,
  hideSaveButton,
  hideSamples,
}: SmartViewBuilderProps) {
  const { t } = useTranslation();

  // ── Property catalog (cached per model) ──────────────────────────────
  const catalogQuery = useQuery<SmartViewPropertyCatalog>({
    queryKey: ['bim-smart-view-properties', modelId],
    enabled: !!modelId,
    queryFn: () => fetchSmartViewProperties(modelId!),
    staleTime: 5 * 60 * 1000,
  });
  const catalog = catalogQuery.data;

  // ── Validation (synchronous, recomputed on tree change) ──────────────
  const report = useMemo(() => validateTree(value), [value]);

  // ── Live count preview (debounced) ───────────────────────────────────
  const [debouncedTree, setDebouncedTree] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedTree(value), 300);
    return () => clearTimeout(t);
  }, [value]);

  const previewQuery = useQuery({
    queryKey: ['bim-smart-view-preview', modelId, projectId, debouncedTree],
    enabled: (!!modelId || !!projectId) && report.treeErrors.length === 0,
    queryFn: () =>
      previewSmartView({
        model_id: modelId,
        project_id: projectId,
        rule_tree: debouncedTree,
        sample_limit: hideSamples ? 0 : 5,
      }),
    staleTime: 30 * 1000,
  });
  const matched = previewQuery.data?.matched_count ?? null;
  const sampleIds = previewQuery.data?.sample_element_ids ?? [];

  // ── Starred + recent saved Smart Views (per project, localStorage) ───
  const shortcuts = useSmartViewShortcuts(projectId);
  const savedViewsQuery = useQuery<BIMElementGroup[]>({
    queryKey: ['bim-element-groups', projectId, modelId],
    enabled: !!projectId,
    queryFn: () => listElementGroups(projectId!, modelId),
    staleTime: 60 * 1000,
  });
  const savedViews = savedViewsQuery.data ?? [];
  const savedById = useMemo(() => {
    const map = new Map<string, BIMElementGroup>();
    for (const g of savedViews) map.set(g.id, g);
    return map;
  }, [savedViews]);

  /** Pull the rule tree out of a saved group's filter_criteria.  Backwards
   *  compat: groups created before Smart View rule trees existed only
   *  carry the legacy chip-based criteria; in that case we just leave
   *  the builder alone. */
  const applySavedView = useCallback(
    (group: BIMElementGroup) => {
      const criteria = group.filter_criteria as Record<string, unknown>;
      const tree = criteria?.rule_tree as SmartViewGroup | undefined;
      if (tree && tree.op && Array.isArray(tree.rules)) {
        onChange(tree);
        shortcuts.pushRecent(group.id);
      }
    },
    [onChange, shortcuts],
  );

  const applyPreset = useCallback(
    (preset: Preset) => {
      onChange(preset.build());
    },
    [onChange],
  );

  // ── Save Smart View modal ────────────────────────────────────────────
  const [saveOpen, setSaveOpen] = useState(false);

  // Shortcuts cross-referenced with the saved-views cache so we render
  // the chip with its real name + color instead of a bare id.
  const starredChips = useMemo(
    () =>
      shortcuts.starred
        .map((id) => savedById.get(id))
        .filter((g): g is BIMElementGroup => !!g),
    [shortcuts.starred, savedById],
  );
  const recentChips = useMemo(
    () =>
      shortcuts.recents
        .map((id) => savedById.get(id))
        .filter((g): g is BIMElementGroup => !!g)
        .filter((g) => !shortcuts.starred.includes(g.id)),
    [shortcuts.recents, shortcuts.starred, savedById],
  );

  return (
    <div className="space-y-3">
      {/* Starred + recent saved views (chip strip, project-scoped) */}
      {(starredChips.length > 0 || recentChips.length > 0) && (
        <div className="space-y-1.5">
          {starredChips.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Star size={11} className="text-amber-500 fill-amber-500" />
                <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('bim.smartview.starred', { defaultValue: 'Starred' })}
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {starredChips.map((g) => (
                  <SavedViewChip
                    key={g.id}
                    group={g}
                    starred
                    onApply={() => applySavedView(g)}
                    onToggleStar={() => shortcuts.toggleStar(g.id)}
                  />
                ))}
              </div>
            </div>
          )}
          {recentChips.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Clock size={11} className="text-content-tertiary" />
                <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('bim.smartview.recent', { defaultValue: 'Recent' })}
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {recentChips.slice(0, 6).map((g) => (
                  <SavedViewChip
                    key={g.id}
                    group={g}
                    starred={false}
                    onApply={() => applySavedView(g)}
                    onToggleStar={() => shortcuts.toggleStar(g.id)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Quick presets */}
      <div>
        <div className="flex items-center gap-1.5 mb-1.5">
          <Zap size={12} className="text-amber-500" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('bim.smartview.presets', { defaultValue: 'Quick presets' })}
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => applyPreset(p)}
              className="px-2 py-1 rounded-md border border-border-light bg-surface-secondary text-[10px] text-content-secondary hover:bg-oe-blue/5 hover:border-oe-blue/30 hover:text-oe-blue transition-colors"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tree-level errors (banner above the tree) */}
      {report.treeErrors.length > 0 && (
        <div
          role="alert"
          className="rounded border border-rose-300 bg-rose-50 dark:bg-rose-950/30 px-2 py-1.5 text-[11px] text-rose-700 dark:text-rose-300"
        >
          <div className="flex items-center gap-1 font-semibold">
            <AlertCircle size={11} />
            {t('bim.smartview.tree_invalid', {
              defaultValue: 'Rule tree is invalid',
            })}
          </div>
          <ul className="ms-4 list-disc">
            {report.treeErrors.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Rule tree */}
      <div>
        <GroupRenderer
          group={value}
          path={[]}
          catalog={catalog}
          onChange={onChange}
          depth={0}
          errors={report.errors}
        />
      </div>

      {/* Live count pill + actions */}
      <div className="flex items-center gap-2 flex-wrap">
        {report.errors.size > 0 ? (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">
            <AlertCircle size={11} />
            {t('bim.smartview.fix_errors', {
              defaultValue: '{{n}} rule errors',
              n: report.errors.size,
            })}
          </span>
        ) : matched === null ? (
          previewQuery.isFetching ? (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] bg-surface-secondary text-content-tertiary">
              {t('bim.smartview.calculating', { defaultValue: 'Calculating…' })}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] bg-surface-secondary text-content-tertiary">
              —
            </span>
          )
        ) : (
          <span
            className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-semibold ${
              matched === 0
                ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300'
                : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
            }`}
            data-testid="smart-view-preview-count"
          >
            {t('bim.smartview.match_count', {
              defaultValue: '{{n}} elements match',
              n: matched,
            })}
          </span>
        )}
        {previewQuery.data?.truncated && (
          <span className="text-[10px] text-amber-600">
            {t('bim.smartview.truncated', {
              defaultValue: 'Scan capped at 50K elements',
            })}
          </span>
        )}
        <span className="text-[10px] text-content-quaternary">
          {t('bim.smartview.leaf_count', {
            defaultValue: '{{n}} of {{max}} rules',
            n: report.leafCount,
            max: MAX_LEAVES,
          })}
        </span>
        {renderActions?.(matched ?? 0)}
        {!hideSaveButton && !renderActions && projectId && (
          <button
            type="button"
            onClick={() => setSaveOpen(true)}
            disabled={report.errors.size > 0 || report.treeErrors.length > 0}
            className="ms-auto inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-oe-blue text-white text-[11px] font-semibold hover:bg-oe-blue/90 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="smart-view-save-button"
          >
            <Save size={11} />
            {t('bim.smartview.save_btn', { defaultValue: 'Save Smart View' })}
          </button>
        )}
      </div>

      {/* Sample matches strip */}
      {!hideSamples && matched !== null && matched > 0 && (
        <SamplePreview modelId={modelId} sampleIds={sampleIds} />
      )}

      {/* Save modal (rendered lazily so it doesn't fire its mount cost
          on every builder usage) */}
      {saveOpen && projectId && (
        <SaveSmartViewModal
          open={saveOpen}
          onClose={() => setSaveOpen(false)}
          projectId={projectId}
          modelId={modelId}
          ruleTree={value}
          matchedCount={matched ?? 0}
          onSaved={(group) => {
            shortcuts.pushRecent(group.id);
          }}
        />
      )}
    </div>
  );
}

/* ── Saved-view chip (used by starred + recent strips) ────────────────── */

interface SavedViewChipProps {
  group: BIMElementGroup;
  starred: boolean;
  onApply: () => void;
  onToggleStar: () => void;
}

function SavedViewChip({
  group,
  starred,
  onApply,
  onToggleStar,
}: SavedViewChipProps) {
  return (
    <div
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border border-border-light bg-surface-secondary text-[10px] hover:border-oe-blue/30"
      style={
        group.color
          ? { borderInlineStartWidth: 3, borderInlineStartColor: group.color }
          : undefined
      }
    >
      <button
        type="button"
        onClick={onApply}
        className="font-medium text-content-primary hover:text-oe-blue truncate max-w-[160px]"
        title={group.description ?? group.name}
      >
        {group.name}
      </button>
      <span className="text-content-quaternary tabular-nums">
        {group.element_count}
      </span>
      <button
        type="button"
        onClick={onToggleStar}
        aria-label={starred ? 'Unstar' : 'Star'}
        className={`p-0.5 rounded ${
          starred
            ? 'text-amber-500 hover:text-amber-600'
            : 'text-content-quaternary hover:text-amber-500'
        }`}
      >
        <Star size={9} className={starred ? 'fill-amber-500' : ''} />
      </button>
    </div>
  );
}

export { isGroup as isSmartViewGroup, PRESETS as SMART_VIEW_PRESETS };
