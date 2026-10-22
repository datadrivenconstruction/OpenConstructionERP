// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMPropertyFilterBar - combinable property conditions plus a chip row for
 * every active filter (search, levels, categories and conditions).
 *
 * Conditions are AND-ed: "Material contains concrete" and "Volume between
 * 1 and 5". Each chip removes its own filter; "Clear all" removes them all.
 */
import { useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, X } from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import {
  BUILTIN_GROUP_KEYS,
  QUANTITY_KEYS,
  discoverPropertyKeys,
  groupValueOf,
  isConditionComplete,
  isQuantityField,
  type ConditionOp,
  type FilterField,
  type GroupKey,
  type PropertyCondition,
} from './bimGrouping';

export interface FilterChip {
  id: string;
  label: string;
  onRemove: () => void;
}

export interface BIMPropertyFilterBarProps {
  elements: BIMElementData[];
  conditions: PropertyCondition[];
  onChange: (next: PropertyCondition[]) => void;
  /** Chips for the panel's own filters (search, levels, categories). */
  baseChips: FilterChip[];
  onClearAll: () => void;
  /** Offer loading every parameter when only the grouping subset is loaded. */
  propertiesLoaded?: boolean;
  propertiesLoading?: boolean;
  onLoadProperties?: () => void;
}

export function useFieldLabel(): (field: FilterField) => string {
  const { t } = useTranslation();
  return (field: FilterField) => {
    switch (field) {
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
      case 'qty:length':
        return t('bim.groupby.col_length', { defaultValue: 'Length (m)' });
      case 'qty:area':
        return t('bim.groupby.col_area', { defaultValue: 'Area (m2)' });
      case 'qty:volume':
        return t('bim.groupby.col_volume', { defaultValue: 'Volume (m3)' });
      default:
        return field.slice('prop:'.length);
    }
  };
}

export default function BIMPropertyFilterBar({
  elements,
  conditions,
  onChange,
  baseChips,
  onClearAll,
  propertiesLoaded = true,
  propertiesLoading,
  onLoadProperties,
}: BIMPropertyFilterBarProps) {
  const { t } = useTranslation();
  const fieldLabel = useFieldLabel();
  const formId = useId();
  const [open, setOpen] = useState(false);
  const [field, setField] = useState<FilterField>('material');
  const [op, setOp] = useState<ConditionOp>('contains');
  const [value, setValue] = useState('');
  const [min, setMin] = useState('');
  const [max, setMax] = useState('');

  const builtins = useMemo(
    () => BUILTIN_GROUP_KEYS.filter((k) => elements.some((el) => groupValueOf(el, k) !== '')),
    [elements],
  );
  const customKeys = useMemo(() => discoverPropertyKeys(elements), [elements]);
  const suggestions = useMemo(() => {
    if (isQuantityField(field)) return [];
    const seen = new Map<string, number>();
    for (const el of elements) {
      const v = groupValueOf(el, field as GroupKey);
      if (v) seen.set(v, (seen.get(v) ?? 0) + 1);
    }
    return [...seen.entries()].sort((a, b) => b[1] - a[1]).slice(0, 50).map(([v]) => v);
  }, [elements, field]);

  const numeric = isQuantityField(field);
  const effectiveOp: ConditionOp = numeric ? 'between' : op === 'between' ? 'contains' : op;
  const parseBound = (raw: string): number | null => {
    const n = Number.parseFloat(raw.replace(',', '.'));
    return Number.isFinite(n) ? n : null;
  };
  const draft: PropertyCondition = {
    field,
    op: op === 'between' ? 'between' : effectiveOp,
    value,
    min: parseBound(min),
    max: parseBound(max),
  };
  const canAdd = isConditionComplete(draft);

  const opLabel = (o: ConditionOp) =>
    ({
      eq: t('bim.pfilter.op_eq', { defaultValue: 'equals' }),
      neq: t('bim.pfilter.op_neq', { defaultValue: 'is not' }),
      contains: t('bim.pfilter.op_contains', { defaultValue: 'contains' }),
      between: t('bim.pfilter.op_between', { defaultValue: 'between' }),
    })[o];

  const conditionLabel = (c: PropertyCondition) => {
    if (c.op === 'between') {
      const lo = c.min ?? null;
      const hi = c.max ?? null;
      if (lo !== null && hi !== null) return `${fieldLabel(c.field)} ${lo} - ${hi}`;
      if (lo !== null) return `${fieldLabel(c.field)} ≥ ${lo}`;
      return `${fieldLabel(c.field)} ≤ ${hi}`;
    }
    return `${fieldLabel(c.field)} ${opLabel(c.op)} "${c.value}"`;
  };

  const add = () => {
    if (!canAdd) return;
    onChange([...conditions, draft]);
    setValue('');
    setMin('');
    setMax('');
    setOpen(false);
  };

  const chips: FilterChip[] = [
    ...baseChips,
    ...conditions.map((c, i) => ({
      id: `cond-${i}`,
      label: conditionLabel(c),
      onRemove: () => onChange(conditions.filter((_, j) => j !== i)),
    })),
  ];

  const inputClass =
    'w-full min-w-0 text-[11px] py-1 px-1.5 rounded border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue';

  return (
    <div className="mt-2 space-y-1.5" data-testid="bim-pfilter">
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1" aria-label={t('bim.pfilter.active', { defaultValue: 'Active filters' })}>
          {chips.map((chip) => (
            <span
              key={chip.id}
              className="inline-flex items-center gap-1 max-w-full ps-2 pe-1 py-0.5 rounded-full bg-oe-blue/10 text-oe-blue text-[10px] font-medium"
              data-testid="bim-pfilter-chip"
            >
              <span className="truncate">{chip.label}</span>
              <button
                type="button"
                onClick={chip.onRemove}
                aria-label={t('bim.pfilter.remove', { defaultValue: 'Remove filter {{name}}', name: chip.label })}
                className="p-0.5 rounded-full hover:bg-oe-blue/20 focus:outline-none focus-visible:ring-1 focus-visible:ring-oe-blue"
              >
                <X size={10} />
              </button>
            </span>
          ))}
          <button
            type="button"
            onClick={onClearAll}
            className="text-[10px] text-content-tertiary hover:text-oe-blue underline-offset-2 hover:underline"
            data-testid="bim-pfilter-clear-all"
          >
            {t('bim.filter_clear', { defaultValue: 'Clear all' })}
          </button>
        </div>
      )}

      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1 text-[11px] font-medium text-oe-blue hover:underline"
          data-testid="bim-pfilter-open"
        >
          <Plus size={12} />
          {t('bim.pfilter.add', { defaultValue: 'Add property filter' })}
        </button>
      ) : (
        <form
          className="p-2 rounded-md border border-border-light bg-surface-secondary space-y-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false);
          }}
          aria-label={t('bim.pfilter.add', { defaultValue: 'Add property filter' })}
        >
          <div className="grid grid-cols-2 gap-1.5">
            <select
              className={inputClass}
              value={field}
              onChange={(e) => {
                const f = e.target.value as FilterField;
                setField(f);
                setOp(isQuantityField(f) ? 'between' : 'contains');
              }}
              aria-label={t('bim.pfilter.field', { defaultValue: 'Property' })}
              data-testid="bim-pfilter-field"
            >
              <optgroup label={t('bim.groupby.builtin_props', { defaultValue: 'Model properties' })}>
                {builtins.map((k) => (
                  <option key={k} value={k}>
                    {fieldLabel(k)}
                  </option>
                ))}
              </optgroup>
              <optgroup label={t('bim.pfilter.quantities', { defaultValue: 'Quantities' })}>
                {QUANTITY_KEYS.map((k) => (
                  <option key={k} value={k}>
                    {fieldLabel(k)}
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
            </select>
            <select
              className={inputClass}
              value={numeric ? 'between' : op}
              disabled={numeric}
              onChange={(e) => setOp(e.target.value as ConditionOp)}
              aria-label={t('bim.pfilter.operator', { defaultValue: 'Condition' })}
              data-testid="bim-pfilter-op"
            >
              {(numeric ? (['between'] as ConditionOp[]) : (['contains', 'eq', 'neq', 'between'] as ConditionOp[])).map(
                (o) => (
                  <option key={o} value={o}>
                    {opLabel(o)}
                  </option>
                ),
              )}
            </select>
          </div>
          {op === 'between' || numeric ? (
            <div className="grid grid-cols-2 gap-1.5">
              <input
                className={inputClass}
                inputMode="decimal"
                value={min}
                onChange={(e) => setMin(e.target.value)}
                placeholder={t('bim.pfilter.min', { defaultValue: 'From' })}
                aria-label={t('bim.pfilter.min', { defaultValue: 'From' })}
                data-testid="bim-pfilter-min"
              />
              <input
                className={inputClass}
                inputMode="decimal"
                value={max}
                onChange={(e) => setMax(e.target.value)}
                placeholder={t('bim.pfilter.max', { defaultValue: 'To' })}
                aria-label={t('bim.pfilter.max', { defaultValue: 'To' })}
                data-testid="bim-pfilter-max"
              />
            </div>
          ) : (
            <>
              <input
                className={inputClass}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                list={`${formId}-values`}
                placeholder={t('bim.pfilter.value', { defaultValue: 'Value' })}
                aria-label={t('bim.pfilter.value', { defaultValue: 'Value' })}
                data-testid="bim-pfilter-value"
              />
              <datalist id={`${formId}-values`}>
                {suggestions.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </>
          )}
          {!propertiesLoaded && onLoadProperties && (
            <button
              type="button"
              onClick={onLoadProperties}
              disabled={propertiesLoading}
              className="text-[10px] text-oe-blue hover:underline disabled:opacity-60"
            >
              {propertiesLoading
                ? t('bim.groupby.loading_params', { defaultValue: 'Loading all parameters...' })
                : t('bim.pfilter.load_params', { defaultValue: 'Load all parameters to filter by custom properties' })}
            </button>
          )}
          <div className="flex justify-end gap-1.5">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="px-2 py-1 rounded text-[11px] text-content-secondary hover:bg-surface-tertiary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type="submit"
              disabled={!canAdd}
              className="px-2.5 py-1 rounded text-[11px] font-semibold bg-oe-blue text-white hover:bg-oe-blue-dark disabled:opacity-40"
              data-testid="bim-pfilter-add"
            >
              {t('bim.pfilter.apply', { defaultValue: 'Add filter' })}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
