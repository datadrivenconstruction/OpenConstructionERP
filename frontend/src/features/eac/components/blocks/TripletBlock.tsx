/**
 * `<TripletBlock>` — paired attribute + constraint shown side-by-side with a
 * thin divider. The triplet is the atomic unit of a predicate (FR-1.6).
 *
 * The shell uses the `attribute` color so the heading reads "Triplet" with
 * the purple identity of an attribute reference; the inner constraint pill
 * keeps the blue identity intact. This dual-color encoding is intentional and
 * matches spec §3.2 — the block-as-a-whole conveys "an attribute paired with
 * a constraint", and screen readers get a clear hierarchy.
 */
import clsx from 'clsx';

import { AttributeBlock } from './AttributeBlock';
import { BlockShell, type BlockShellProps } from './BlockShell';
import { ConstraintBlock } from './ConstraintBlock';
import type { AttributeRef, Constraint } from '../../types';

type ForwardedShellProps = Omit<BlockShellProps, 'color' | 'children' | 'label'>;

export interface TripletBlockProps extends ForwardedShellProps {
  attribute: AttributeRef;
  constraint: Constraint;
  label?: string;
  /** Click handler on the inner attribute slot. */
  onAttributeSelect?: () => void;
  /** Click handler on the inner constraint slot. */
  onConstraintSelect?: () => void;
  /** Selected state of the attribute slot. */
  attributeSelected?: boolean;
  /** Selected state of the constraint slot. */
  constraintSelected?: boolean;
}

export function TripletBlock({
  attribute,
  constraint,
  label,
  onAttributeSelect,
  onConstraintSelect,
  attributeSelected,
  constraintSelected,
  className,
  ...shellProps
}: TripletBlockProps) {
  return (
    <BlockShell
      color="attribute"
      label={label ?? 'Triplet'}
      className={clsx('!gap-2', className)}
      testId="eac-block-triplet"
      {...shellProps}
    >
      <div
        className="flex items-stretch gap-2"
        role="group"
        aria-label="Attribute and constraint pair"
      >
        <div className="flex-1 min-w-0">
          <AttributeBlock
            attribute={attribute}
            onSelect={onAttributeSelect}
            selected={attributeSelected}
            testId="eac-triplet-attribute"
          />
        </div>
        <div
          aria-hidden="true"
          className="self-stretch w-px bg-purple-300 dark:bg-purple-700"
        />
        <div className="flex-1 min-w-0">
          <ConstraintBlock
            constraint={constraint}
            onSelect={onConstraintSelect}
            selected={constraintSelected}
            testId="eac-triplet-constraint"
          />
        </div>
      </div>
    </BlockShell>
  );
}
