/**
 * Storybook stories for `<AttributeBlock>`.
 */
import { DndContext } from '@dnd-kit/core';
import type { Meta, StoryObj } from '@storybook/react';

import { AttributeBlock } from './AttributeBlock';

const meta: Meta<typeof AttributeBlock> = {
  title: 'EAC/Blocks/AttributeBlock',
  component: AttributeBlock,
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

type Story = StoryObj<typeof AttributeBlock>;

export const ExactWithPset: Story = {
  args: {
    attribute: {
      kind: 'exact',
      pset_name: 'Pset_WallCommon',
      property_name: 'IsExternal',
    },
  },
};

export const ExactInstance: Story = {
  args: { attribute: { kind: 'exact', property_name: 'GlobalId', pset_name: null } },
};

export const Alias: Story = {
  args: {
    attribute: { kind: 'alias', alias_id: 'eac.alias.thickness', canonical_name: 'Thickness' },
  },
};

export const Regex: Story = {
  args: {
    attribute: { kind: 'regex', pattern: '^Pset_', scope: 'pset_name' },
  },
};

export const Selected: Story = {
  args: {
    attribute: { kind: 'alias', alias_id: 'a1', canonical_name: 'Length' },
    selected: true,
    onSelect: () => {},
  },
};

export const Draggable: Story = {
  args: {
    attribute: { kind: 'alias', alias_id: 'a1', canonical_name: 'Length' },
    draggable: true,
    sortableId: 'a1',
  },
};
