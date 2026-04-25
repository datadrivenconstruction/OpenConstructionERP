/**
 * Storybook stories for `<VariableBlock>`.
 */
import { DndContext } from '@dnd-kit/core';
import type { Meta, StoryObj } from '@storybook/react';

import { VariableBlock } from './VariableBlock';

const meta: Meta<typeof VariableBlock> = {
  title: 'EAC/Blocks/VariableBlock',
  component: VariableBlock,
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

type Story = StoryObj<typeof VariableBlock>;

export const SumExpression: Story = {
  args: {
    variable: {
      name: 'totalWallVolume',
      aggregate: 'sum',
      expression: '${Volume}',
      unit: 'm³',
    },
  },
};

export const CountDistinct: Story = {
  args: {
    variable: { name: 'distinctMaterials', aggregate: 'count_distinct', expression: '${Material}' },
  },
};

export const PlainExpression: Story = {
  args: { variable: { name: 'thickInM', expression: '${Thickness} / 1000', unit: 'm' } },
};

export const Selected: Story = {
  args: {
    variable: { name: 'avgArea', aggregate: 'avg', expression: '${Area}', unit: 'm²' },
    selected: true,
    onSelect: () => {},
  },
};

export const Draggable: Story = {
  args: {
    variable: { name: 'avgArea', aggregate: 'avg', expression: '${Area}', unit: 'm²' },
    draggable: true,
    sortableId: 'v1',
  },
};
