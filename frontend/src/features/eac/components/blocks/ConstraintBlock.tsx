/**
 * `<ConstraintBlock>` — blue block showing operator + value(s).
 *
 * Renders a compact summary like `≥ 240 mm` or `between 100 and 200`.
 * The actual editing UX (operator picker, value inputs) is owned by the
 * inspector panel (EAC-3.2 / EAC-3.4).
 */
import { BlockShell, type BlockShellProps } from './BlockShell';
import type { Constraint, ConstraintOperator } from '../../types';

type ForwardedShellProps = Omit<BlockShellProps, 'color' | 'children' | 'label'>;

export interface ConstraintBlockProps extends ForwardedShellProps {
  constraint: Constraint;
  label?: string;
}

/** Map operator → short symbol shown in the summary. */
const OPERATOR_SYMBOL: Record<ConstraintOperator, string> = {
  eq: '=',
  ne: '≠',
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
  between: 'between',
  not_between: 'not between',
  in: 'in',
  not_in: 'not in',
  starts_with: 'starts with',
  ends_with: 'ends with',
  contains: 'contains',
  not_contains: 'does not contain',
  matches: 'matches',
  not_matches: 'does not match',
  exists: 'exists',
  not_exists: 'does not exist',
  is_null: 'is null',
  is_not_null: 'is not null',
  is_numeric: 'is numeric',
  is_string: 'is string',
  is_boolean: 'is boolean',
  eq_unit_aware: '= (unit)',
  gte_unit_aware: '≥ (unit)',
  lte_unit_aware: '≤ (unit)',
};

/** True if the operator does not take a right-hand side value. */
const UNARY_OPERATORS = new Set<ConstraintOperator>([
  'exists',
  'not_exists',
  'is_null',
  'is_not_null',
  'is_numeric',
  'is_string',
  'is_boolean',
]);

const RANGE_OPERATORS = new Set<ConstraintOperator>(['between', 'not_between']);
const SET_OPERATORS = new Set<ConstraintOperator>(['in', 'not_in']);

/** Compact human description for a constraint. */
export function describeConstraint(constraint: Constraint): string {
  const symbol = OPERATOR_SYMBOL[constraint.operator] ?? constraint.operator;

  if (UNARY_OPERATORS.has(constraint.operator)) {
    return symbol;
  }

  if (RANGE_OPERATORS.has(constraint.operator)) {
    const [min, max] = constraint.values ?? [];
    const unit = constraint.unit ? ` ${constraint.unit}` : '';
    return `${symbol} ${min ?? '?'} … ${max ?? '?'}${unit}`;
  }

  if (SET_OPERATORS.has(constraint.operator)) {
    const set = (constraint.values ?? []).join(', ');
    return `${symbol} {${set || '…'}}`;
  }

  const value = constraint.value ?? '?';
  const unit = constraint.unit ? ` ${constraint.unit}` : '';
  return `${symbol} ${value}${unit}`;
}

export function ConstraintBlock({ constraint, label, ...shellProps }: ConstraintBlockProps) {
  const summary = describeConstraint(constraint);
  return (
    <BlockShell color="constraint" label={label ?? 'Constraint'} {...shellProps}>
      {summary}
    </BlockShell>
  );
}
