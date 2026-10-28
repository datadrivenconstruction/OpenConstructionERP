// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One property condition of a quantity rule: property, comparison, value.
 *
 * For "equals" and "not equals" the value field offers the values the model
 * carries, from the same per-property value list the property search shows
 * (``useColumnValueOptions``); without a property table it falls back to the
 * catalog's sample values. The empty checks take no value. A value the
 * comparison cannot use is named under the row, in the reader's language,
 * and the editor will not save until it is fixed.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2 } from 'lucide-react';
import type { BIMDataframeColumn } from './api';
import { isWildcardSample } from './rulePropertyCatalog';
import {
  NUMERIC_OPERATORS,
  RULE_OPERATORS,
  VALUELESS_OPERATORS,
  VALUE_LIST_OPERATORS,
  type CheckedCondition,
  type RuleOperator,
} from './ruleOperators';
import { useColumnValueOptions } from './useColumnValueOptions';

export interface ConditionRowState {
  key: string;
  op: RuleOperator;
  value: string;
}

interface RuleConditionRowProps {
  index: number;
  row: ConditionRowState;
  checked: CheckedCondition;
  modelId: string | null | undefined;
  schema: readonly BIMDataframeColumn[] | undefined;
  /** Catalog sample values for this property (fallback list). */
  samples: readonly string[];
  keyListId: string;
  valueListId: string;
  onChange: (field: keyof ConditionRowState, value: string) => void;
  onRemove: () => void;
}

/** The property-table column a typed key names: exact name, then the
 *  exported header, then either case-insensitively. */
export function resolveDataframeColumn(
  schema: readonly BIMDataframeColumn[] | undefined,
  key: string,
): string {
  const wanted = key.trim();
  if (!wanted || !schema) return '';
  const lower = wanted.toLowerCase();
  const hit =
    schema.find((c) => c.name === wanted) ??
    schema.find((c) => c.label === wanted) ??
    schema.find((c) => c.name.trim().toLowerCase() === lower || (c.label ?? '').trim().toLowerCase() === lower);
  return hit?.name ?? '';
}

export function RuleConditionRow({
  index,
  row,
  checked,
  modelId,
  schema,
  samples,
  keyListId,
  valueListId,
  onChange,
  onRemove,
}: RuleConditionRowProps) {
  const { t } = useTranslation();
  const column = useMemo(() => resolveDataframeColumn(schema, row.key), [schema, row.key]);
  const wantsValues = VALUE_LIST_OPERATORS.has(row.op);
  const values = useColumnValueOptions(modelId, column, wantsValues && !!column);
  const valueChoices = useMemo(
    () => (values.items.length > 0 ? values.items.map((v) => v.value) : [...samples]),
    [values.items, samples],
  );

  const opLabel = (op: RuleOperator): string => {
    switch (op) {
      case 'equals':
        return t('bim_rules.op_equals', { defaultValue: 'equals' });
      case 'not_equals':
        return t('bim_rules.op_not_equals', { defaultValue: 'does not equal' });
      case 'contains':
        return t('bim_rules.op_contains', { defaultValue: 'contains' });
      case 'not_contains':
        return t('bim_rules.op_not_contains', { defaultValue: 'does not contain' });
      case 'gt':
        return t('bim_rules.op_gt', { defaultValue: 'greater than' });
      case 'gte':
        return t('bim_rules.op_gte', { defaultValue: 'greater than or equal' });
      case 'lt':
        return t('bim_rules.op_lt', { defaultValue: 'less than' });
      case 'lte':
        return t('bim_rules.op_lte', { defaultValue: 'less than or equal' });
      case 'is_empty':
        return t('bim_rules.op_is_empty', { defaultValue: 'is empty' });
      case 'is_not_empty':
        return t('bim_rules.op_is_not_empty', { defaultValue: 'is not empty' });
    }
  };

  const problemText = (): string | null => {
    switch (checked.problem) {
      case 'value_required':
        return t('bim_rules.cond_value_required', { defaultValue: 'This comparison needs a value.' });
      case 'value_not_number':
        return t('bim_rules.cond_value_not_number', {
          defaultValue: 'Write a number, with a unit such as mm, m, m2, m3 or kg if you need one.',
        });
      case 'value_too_long':
        return t('bim_rules.cond_value_too_long', { defaultValue: 'This value is too long, 500 characters at most.' });
      default:
        return null;
    }
  };
  const problem = problemText();
  const placeholder = NUMERIC_OPERATORS.has(row.op)
    ? t('bim_rules.cond_value_number_placeholder', { defaultValue: 'Number, e.g. 2.5 m' })
    : t('bim_rules.property_value', { defaultValue: 'Value (wildcards OK)' });

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
        <input
          type="text"
          value={row.key}
          onChange={(e) => onChange('key', e.target.value)}
          list={keyListId}
          autoComplete="off"
          data-testid={`rule-prop-key-${index}`}
          aria-label={t('bim_rules.property_key', { defaultValue: 'Property key' })}
          placeholder={t('bim_rules.property_key', { defaultValue: 'Property key' })}
          className="min-w-0 flex-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 font-mono text-xs text-content-primary focus:border-oe-blue focus:outline-none"
        />
        <select
          value={row.op}
          onChange={(e) => onChange('op', e.target.value)}
          data-testid={`rule-prop-op-${index}`}
          aria-label={t('bim_rules.cond_operator', { defaultValue: 'Comparison' })}
          className="shrink-0 rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
        >
          {RULE_OPERATORS.map((op) => (
            <option key={op} value={op}>
              {opLabel(op)}
            </option>
          ))}
        </select>
        {!VALUELESS_OPERATORS.has(row.op) && (
          <>
            <input
              type="text"
              value={row.value}
              onChange={(e) => onChange('value', e.target.value)}
              list={wantsValues ? valueListId : undefined}
              autoComplete="off"
              inputMode={NUMERIC_OPERATORS.has(row.op) ? 'decimal' : undefined}
              data-testid={`rule-prop-value-${index}`}
              aria-label={placeholder}
              aria-invalid={problem ? true : undefined}
              placeholder={placeholder}
              className={`min-w-0 flex-1 rounded-lg border bg-surface-primary px-2 py-1.5 font-mono text-xs text-content-primary focus:border-oe-blue focus:outline-none ${
                problem ? 'border-red-500' : 'border-border-light'
              }`}
            />
            {wantsValues && (
              <datalist id={valueListId}>
                {valueChoices.map((v) => (
                  <option key={v} value={v} />
                ))}
              </datalist>
            )}
          </>
        )}
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-red-600"
          aria-label={t('common.remove', { defaultValue: 'Remove' })}
        >
          <Trash2 size={13} />
        </button>
      </div>
      {wantsValues && values.items.length > 0 && values.items.length < values.total && (
        <button
          type="button"
          disabled={values.loading}
          onClick={values.loadMore}
          data-testid={`rule-prop-values-more-${index}`}
          className="mt-1 text-[11px] text-oe-blue disabled:opacity-50"
        >
          {t('boq.load_more', { defaultValue: 'Load more' })} ({values.items.length} / {values.total})
        </button>
      )}
      {problem && (
        <p data-testid={`rule-prop-problem-${index}`} role="alert" className="mt-1 text-[11px] text-red-600">
          {problem}
        </p>
      )}
      {!problem && checked.ambiguous && (
        <p data-testid={`rule-prop-read-as-${index}`} className="mt-1 text-[11px] text-content-tertiary">
          {t('bim_rules.cond_read_as', { defaultValue: 'Read as {{value}}', value: checked.value })}
        </p>
      )}
      {wantsValues && isWildcardSample(row.value, valueChoices) && (
        <p
          data-testid={`rule-prop-wildcard-hint-${index}`}
          className="mt-1 text-[11px] text-amber-700 dark:text-amber-400"
        >
          {t('bim_rules.value_has_wildcard', {
            defaultValue:
              'This value contains * or ?, which match any text in a rule, so it can pick more elements than this exact value.',
          })}
        </p>
      )}
    </>
  );
}
