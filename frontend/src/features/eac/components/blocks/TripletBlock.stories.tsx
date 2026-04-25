/**
 * Storybook stories for `<TripletBlock>`.
 */
import { DndContext } from '@dnd-kit/core';
import type { Meta, StoryObj } from '@storybook/react';

import { TripletBlock } from './TripletBlock';

const meta: Meta<typeof TripletBlock> = {
  title: 'EAC/Blocks/TripletBlock',
  component: TripletBlock,
  decorators: [
    (Story) => (
      <DndContext>
        <div className="max-w-md p-4">
          <Story />
        </div>
      </DndContext>
    ),
  ],
  parameters: { a11y: { config: { rules: [{ id: 'color-contrast', enabled: true }] } } },
};
export default meta;

type Story = StoryObj<typeof TripletBlock>;

export const ExactPropertyEquals: Story = {
  args: {
    attribute: { kind: 'exact', pset_name: 'Pset_WallCommon', property_name: 'IsExternal' },
    constraint: { operator: 'eq', value: true },
  },
};

export const AliasGte: Story = {
  args: {
    attribute: { kind: 'alias', alias_id: 'a1', canonical_name: 'Thickness' },
    constraint: { operator: 'gte', value: 240, unit: 'mm' },
  },
};

export const Selected: Story = {
  args: {
    attribute: { kind: 'alias', alias_id: 'a1', canonical_name: 'Length' },
    constraint: { operator: 'between', values: [1, 5], unit: 'm' },
    selected: true,
    onSelect: () => {},
  },
};

export const InnerSelected: Story = {
  args: {
    attribute: { kind: 'alias', alias_id: 'a1', canonical_name: 'Length' },
    constraint: { operator: 'gte', value: 1, unit: 'm' },
    attributeSelected: true,
    onAttributeSelect: () => {},
    onConstraintSelect: () => {},
  },
};

export const Draggable: Story = {
  args: {
    attribute: { kind: 'alias', alias_id: 'a1', canonical_name: 'Thickness' },
    constraint: { operator: 'gte', value: 240, unit: 'mm' },
    draggable: true,
    sortableId: 't1',
  },
};
