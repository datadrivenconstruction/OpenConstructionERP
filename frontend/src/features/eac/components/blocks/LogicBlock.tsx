/**
 * `<LogicBlock>` — green block representing an AND / OR / NOT predicate.
 *
 * The block itself only shows the operator badge and child count. The actual
 * children render below as nested `<TripletBlock>` / `<LogicBlock>` instances
 * — that recursion is owned by the canvas (EAC-3.2).
 */
import { BlockShell, type BlockShellProps } from './BlockShell';
import type { LogicKind } from '../../types';

type ForwardedShellProps = Omit<BlockShellProps, 'color' | 'children' | 'label'>;

export interface LogicBlockProps extends ForwardedShellProps {
  kind: LogicKind;
  /**
   * Number of children attached. NOT always shows 1; AND/OR show n.
   */
  childCount: number;
  label?: string;
}

const KIND_LABEL: Record<LogicKind, string> = {
  and: 'AND',
  or: 'OR',
  not: 'NOT',
};

export function LogicBlock({ kind, childCount, label, ...shellProps }: LogicBlockProps) {
  const operator = KIND_LABEL[kind];
  const summary =
    kind === 'not'
      ? '1 child'
      : `${childCount} child${childCount === 1 ? '' : 'ren'}`;

  return (
    <BlockShell color="logic" label={label ?? operator} {...shellProps}>
      {summary}
    </BlockShell>
  );
}
