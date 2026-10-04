// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<LogicBlock>` — green block representing an AND / OR / NOT predicate.
 *
 * The block itself only shows the operator badge and child count. The actual
 * children render below as nested `<TripletBlock>` / `<LogicBlock>` instances
 * — that recursion is owned by the canvas (EAC-3.2).
 */
import { useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
  const operator = KIND_LABEL[kind];
  // NOT negates exactly one condition, whatever the canvas reports.
  const summary = t('eac.logic_block.conditions_count', {
    count: kind === 'not' ? 1 : childCount,
    defaultValue_one: '{{count}} condition',
    defaultValue_other: '{{count}} conditions',
  });

  return (
    <BlockShell color="logic" label={label ?? operator} {...shellProps}>
      {summary}
    </BlockShell>
  );
}
