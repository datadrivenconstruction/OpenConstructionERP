/**
 * Storybook stories for `<ConstraintBlock>`.
 */
import { DndContext } from '@dnd-kit/core';
import type { Meta, StoryObj } from '@storybook/react';

import { ConstraintBlock } from './ConstraintBlock';

const meta: Meta<typeof ConstraintBlock> = {
  title: 'EAC/Blocks/ConstraintBlock',
  component: ConstraintBlock,
  decorators: [
    (Story) => (
      <DndContext>
        <div className="max-w-sm p-4">
          <Story />
        </div>
      </DndContext>
    ),
  ],
  parameters: { a11y: { config: { rules: [{ id: 'color-contrast', enabled: true }] } } },
};
export default meta;

type Story = StoryObj<typeof ConstraintBlock>;

export const GreaterEqual: Story = {
  args: { constraint: { operator: 'gte', value: 240, unit: 'mm' } },
};

export const Between: Story = {
  args: { constraint: { operator: 'between', values: [100, 200], unit: 'mm' } },
};

export const InSet: Story = {
  args: { constraint: { operator: 'in', values: ['A', 'B', 'C'] } },
};

export const Exists: Story = {
  args: { constraint: { operator: 'exists' } },
};

export const RegexMatch: Story = {
  args: { constraint: { operator: 'matches', value: '^F[0-9]+$' } },
};

export const Selected: Story = {
  args: {
    constraint: { operator: 'gte', value: 240, unit: 'mm' },
    selected: true,
    onSelect: () => {},
  },
};

export const Draggable: Story = {
  args: {
    constraint: { operator: 'gte', value: 240, unit: 'mm' },
    draggable: true,
    sortableId: 'c1',
  },
};
