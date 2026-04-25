/**
 * `<SelectorBlock>` — gray block representing an `EntitySelector`.
 *
 * Shows the selector kind in the header and a brief value summary below.
 * For composite selectors (and/or/not), the summary includes child count;
 * the canvas renders the children as nested blocks.
 */
import { BlockShell, type BlockShellProps } from './BlockShell';
import type { EntitySelector } from '../../types';

type ForwardedShellProps = Omit<BlockShellProps, 'color' | 'children' | 'label'>;

export interface SelectorBlockProps extends ForwardedShellProps {
  selector: EntitySelector;
  /** Optional label override. Default uses the selector kind. */
  label?: string;
}

/** Compact human description for a selector. */
export function describeSelector(selector: EntitySelector): string {
  switch (selector.type) {
    case 'ifc_class':
      return `IFC: ${selector.ifc_class}${selector.include_subtypes ? ' (+ subtypes)' : ''}`;
    case 'category':
      return `Category: ${selector.category}`;
    case 'classification': {
      const codes = selector.codes?.length
        ? selector.codes.join(', ')
        : (selector.code ?? '—');
      return `Classification: ${codes}`;
    }
    case 'spatial':
      return `${selector.scope}: ${selector.ref_id}`;
    case 'attribute':
      return 'Attribute predicate';
    case 'and':
      return `AND ${selector.children.length} children`;
    case 'or':
      return `OR ${selector.children.length} children`;
    case 'not':
      return 'NOT';
    default: {
      // Exhaustiveness check — TypeScript will error if a case is missing.
      const _exhaustive: never = selector;
      return String(_exhaustive);
    }
  }
}

export function SelectorBlock({ selector, label, ...shellProps }: SelectorBlockProps) {
  const summary = describeSelector(selector);
  return (
    <BlockShell
      color="selector"
      label={label ?? `Selector · ${selector.type}`}
      {...shellProps}
    >
      {summary}
    </BlockShell>
  );
}
