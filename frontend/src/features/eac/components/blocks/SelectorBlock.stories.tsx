/**
 * Storybook stories for `<SelectorBlock>`.
 */
import { DndContext } from '@dnd-kit/core';
import type { Meta, StoryObj } from '@storybook/react';

import { SelectorBlock } from './SelectorBlock';

const meta: Meta<typeof SelectorBlock> = {
  title: 'EAC/Blocks/SelectorBlock',
  component: SelectorBlock,
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

type Story = StoryObj<typeof SelectorBlock>;

export const Category: Story = {
  args: { selector: { type: 'category', category: 'Walls' } },
};

export const IfcClass: Story = {
  args: { selector: { type: 'ifc_class', ifc_class: 'IfcWall', include_subtypes: true } },
};

export const Classification: Story = {
  args: {
    selector: {
      type: 'classification',
      classifier_id: 'uniformat',
      codes: ['B2010', 'B2020'],
    },
  },
};

export const Spatial: Story = {
  args: { selector: { type: 'spatial', scope: 'level', ref_id: 'L1' } },
};

export const AndComposite: Story = {
  args: {
    selector: {
      type: 'and',
      children: [
        { type: 'category', category: 'Walls' },
        { type: 'attribute', predicate: { type: 'and', children: [] } },
      ],
    },
  },
};

export const Selected: Story = {
  args: {
    selector: { type: 'category', category: 'Walls' },
    selected: true,
    onSelect: () => {},
  },
};

export const Draggable: Story = {
  args: {
    selector: { type: 'category', category: 'Walls' },
    draggable: true,
    sortableId: 's1',
  },
};
