/**
 * Storybook stories for `<EacBlockPalette>`.
 *
 * The palette must always be wrapped in a `DndContext` because the
 * `<DraggablePaletteItem>` children call `useDraggable`. Stories provide one
 * via the decorator.
 */
import { DndContext } from '@dnd-kit/core';
import type { Meta, StoryObj } from '@storybook/react';
import { useState } from 'react';

import { EacBlockPalette } from './EacBlockPalette';

const meta: Meta<typeof EacBlockPalette> = {
  title: 'EAC/Palette',
  component: EacBlockPalette,
  decorators: [
    (Story) => (
      <DndContext>
        <div className="flex h-[600px] bg-surface-primary">
          <Story />
        </div>
      </DndContext>
    ),
  ],
  parameters: {
    a11y: { config: { rules: [{ id: 'color-contrast', enabled: true }] } },
  },
};
export default meta;

type Story = StoryObj<typeof EacBlockPalette>;

export const Default: Story = {};

export const Collapsed: Story = {
  args: { collapsed: true },
};

export const SearchActive: Story = {
  render: () => {
    function HostedPalette() {
      const [last, setLast] = useState<string | null>(null);
      return (
        <div className="flex">
          <EacBlockPalette onActivate={(item) => setLast(item.label)} />
          <div className="p-4 text-xs text-content-secondary">
            Try searching for <code>between</code> or <code>alias</code>.
            {last && <div className="mt-2">Last activated: {last}</div>}
          </div>
        </div>
      );
    }
    return <HostedPalette />;
  },
};
