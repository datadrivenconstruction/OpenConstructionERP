/**
 * Storybook stories for `<LogicBlock>`.
 */
import { DndContext } from '@dnd-kit/core';
import type { Meta, StoryObj } from '@storybook/react';

import { LogicBlock } from './LogicBlock';

const meta: Meta<typeof LogicBlock> = {
  title: 'EAC/Blocks/LogicBlock',
  component: LogicBlock,
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

type Story = StoryObj<typeof LogicBlock>;

export const And: Story = { args: { kind: 'and', childCount: 2 } };
export const Or: Story = { args: { kind: 'or', childCount: 3 } };
export const Not: Story = { args: { kind: 'not', childCount: 1 } };
export const Selected: Story = {
  args: { kind: 'and', childCount: 2, selected: true, onSelect: () => {} },
};
export const Draggable: Story = {
  args: { kind: 'or', childCount: 2, draggable: true, sortableId: 'l1' },
};
