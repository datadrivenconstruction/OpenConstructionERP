/**
 * Storybook stories for `<BlockShell>`.
 *
 * NOTE: Storybook isn't yet installed in this repo; these story files are
 * written to be ready as soon as `@storybook/react-vite` lands. They use the
 * CSF3 format that both Storybook 8.x and 9.x understand.
 *
 * The `parameters.a11y` block configures the `@storybook/addon-a11y` axe-core
 * rules. When the addon is installed, every story will be scanned automatically.
 */
import { DndContext } from '@dnd-kit/core';
import { Star } from 'lucide-react';
import type { Meta, StoryObj } from '@storybook/react';

import { BlockShell } from './BlockShell';

const meta: Meta<typeof BlockShell> = {
  title: 'EAC/Blocks/BlockShell',
  component: BlockShell,
  decorators: [
    (Story) => (
      <DndContext>
        <div className="max-w-sm p-4">
          <Story />
        </div>
      </DndContext>
    ),
  ],
  parameters: {
    a11y: {
      config: { rules: [{ id: 'color-contrast', enabled: true }] },
    },
  },
};
export default meta;

type Story = StoryObj<typeof BlockShell>;

export const Default: Story = {
  args: { color: 'selector' },
};

export const Selected: Story = {
  args: { color: 'selector', selected: true, onSelect: () => {} },
};

export const Draggable: Story = {
  args: { color: 'logic', draggable: true, sortableId: 'demo-1' },
};

export const WithCustomIconAndLabel: Story = {
  args: {
    color: 'attribute',
    label: 'Starred attribute',
    icon: <Star size={16} aria-hidden="true" />,
    children: 'Custom body content',
  },
};

export const WithoutChildren: Story = {
  args: { color: 'variable', label: 'Variable' },
};

export const AllColors: Story = {
  render: () => (
    <div className="flex flex-col gap-2">
      <BlockShell color="selector">Selector body</BlockShell>
      <BlockShell color="logic">Logic body</BlockShell>
      <BlockShell color="attribute">Attribute body</BlockShell>
      <BlockShell color="constraint">Constraint body</BlockShell>
      <BlockShell color="variable">Variable body</BlockShell>
    </div>
  ),
};
