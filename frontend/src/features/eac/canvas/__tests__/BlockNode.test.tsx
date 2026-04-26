/**
 * Unit tests for the canvas <BlockNode> component.
 *
 * We mock @xyflow/react so the test runs in jsdom without ResizeObserver
 * gymnastics. The mock supplies stub implementations for `Handle` /
 * `Position` / `NodeProps`-shaped data — we only render the component, not
 * the surrounding flow graph.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

vi.mock('@xyflow/react', () => ({
  Handle: ({ id, type }: { id: string; type: string }) => (
    <span data-testid={`handle-${type}-${id}`} />
  ),
  Position: { Left: 'left', Right: 'right' },
}));

import { BlockNode, type BlockNodeProps } from '../BlockNode';
import { useBlockCanvasStore } from '../useBlockCanvasStore';
import type { CanvasBlock } from '../useBlockCanvasStore';

function makeBlock(overrides: Partial<CanvasBlock> = {}): CanvasBlock {
  return {
    id: 'blk-1',
    kind: 'and',
    color: 'logic',
    title: 'AND',
    position: { x: 0, y: 0 },
    slots: [
      { id: 'in', label: 'in', direction: 'input', dataType: 'predicate' },
      { id: 'out', label: 'out', direction: 'output', dataType: 'predicate' },
    ],
    params: { type: 'and', threshold: 240 },
    expanded: false,
    ...overrides,
  };
}

function nodeProps(block: CanvasBlock): BlockNodeProps {
  return {
    id: block.id,
    data: { block } as unknown as BlockNodeProps['data'],
    type: 'eacBlock',
    selected: false,
    dragging: false,
    draggable: true,
    isConnectable: true,
    selectable: true,
    deletable: true,
    zIndex: 0,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
  } as BlockNodeProps;
}

describe('BlockNode', () => {
  it('renders block title and parameter chips', () => {
    const block = makeBlock();
    render(<BlockNode {...nodeProps(block)} />);
    expect(screen.getByTestId('eac-block-node-blk-1')).toBeInTheDocument();
    expect(screen.getByText('AND')).toBeInTheDocument();
    expect(screen.getByText('type')).toBeInTheDocument();
    expect(screen.getByText('threshold')).toBeInTheDocument();
  });

  it('renders input + output handles for each slot', () => {
    const block = makeBlock();
    render(<BlockNode {...nodeProps(block)} />);
    expect(screen.getByTestId('handle-target-in')).toBeInTheDocument();
    expect(screen.getByTestId('handle-source-out')).toBeInTheDocument();
  });

  it('toggles expanded state via the chevron button', () => {
    useBlockCanvasStore.getState().reset();
    const id = useBlockCanvasStore.getState().addBlock(
      { kind: 'and', color: 'logic', payload: { a: 1, b: 2, c: 3, d: 4, e: 5 }, position: { x: 0, y: 0 }, label: 'AND' },
      [],
    );
    const block = useBlockCanvasStore.getState().blocks.find((b) => b.id === id);
    if (!block) throw new Error('block missing');
    render(<BlockNode {...nodeProps(block)} />);
    const toggle = screen.getByTestId(`eac-block-node-toggle-${id}`);
    fireEvent.click(toggle);
    const after = useBlockCanvasStore.getState().blocks.find((b) => b.id === id);
    expect(after?.expanded).toBe(true);
  });

  it('enters title-edit mode on double click and commits on Enter', () => {
    useBlockCanvasStore.getState().reset();
    const id = useBlockCanvasStore.getState().addBlock(
      { kind: 'and', color: 'logic', payload: {}, position: { x: 0, y: 0 }, label: 'AND' },
      [],
    );
    const block = useBlockCanvasStore.getState().blocks.find((b) => b.id === id);
    if (!block) throw new Error('block missing');
    render(<BlockNode {...nodeProps(block)} />);
    fireEvent.doubleClick(screen.getByTestId(`eac-block-node-title-${id}`));
    const input = screen.getByTestId(`eac-block-node-title-input-${id}`) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Renamed' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    const after = useBlockCanvasStore.getState().blocks.find((b) => b.id === id);
    expect(after?.title).toBe('Renamed');
  });
});
