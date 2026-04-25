/**
 * `<AttributeBlock>` — purple block referencing an attribute (exact / alias /
 * regex). Always lives inside a `<TripletBlock>` together with a constraint.
 */
import { BlockShell, type BlockShellProps } from './BlockShell';
import type { AttributeRef } from '../../types';

type ForwardedShellProps = Omit<BlockShellProps, 'color' | 'children' | 'label'>;

export interface AttributeBlockProps extends ForwardedShellProps {
  attribute: AttributeRef;
  label?: string;
}

/** Compact human description for an attribute reference. */
export function describeAttribute(attribute: AttributeRef): string {
  switch (attribute.kind) {
    case 'exact': {
      const pset = attribute.pset_name?.trim();
      return pset
        ? `${pset}.${attribute.property_name}`
        : attribute.property_name;
    }
    case 'alias':
      return attribute.canonical_name
        ? `${attribute.canonical_name} (alias)`
        : `alias:${attribute.alias_id}`;
    case 'regex':
      return `/${attribute.pattern}/ (${attribute.scope})`;
    default: {
      const _exhaustive: never = attribute;
      return String(_exhaustive);
    }
  }
}

const KIND_LABEL: Record<AttributeRef['kind'], string> = {
  exact: 'Property',
  alias: 'Alias',
  regex: 'Regex',
};

export function AttributeBlock({ attribute, label, ...shellProps }: AttributeBlockProps) {
  const summary = describeAttribute(attribute);
  return (
    <BlockShell
      color="attribute"
      label={label ?? KIND_LABEL[attribute.kind]}
      {...shellProps}
    >
      {summary}
    </BlockShell>
  );
}
