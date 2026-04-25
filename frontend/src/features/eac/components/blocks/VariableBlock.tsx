/**
 * `<VariableBlock>` — yellow block showing a local variable definition.
 *
 * Format: `name = aggregate(...)` or `name = expression`.
 */
import { BlockShell, type BlockShellProps } from './BlockShell';
import type { LocalVariableDefinition } from '../../types';

type ForwardedShellProps = Omit<BlockShellProps, 'color' | 'children' | 'label'>;

export interface VariableBlockProps extends ForwardedShellProps {
  variable: LocalVariableDefinition;
  label?: string;
}

/** Compact human description for a local variable. */
export function describeVariable(variable: LocalVariableDefinition): string {
  const lhs = variable.name || '(unnamed)';
  if (variable.aggregate) {
    const arg = variable.expression ?? variable.source?.kind ?? '…';
    return `${lhs} = ${variable.aggregate}(${arg})`;
  }
  if (variable.expression) {
    return `${lhs} = ${variable.expression}`;
  }
  return lhs;
}

export function VariableBlock({ variable, label, ...shellProps }: VariableBlockProps) {
  const summary = describeVariable(variable);
  return (
    <BlockShell color="variable" label={label ?? 'Variable'} {...shellProps}>
      {summary}
    </BlockShell>
  );
}
