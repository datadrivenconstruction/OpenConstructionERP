/**
 * Tests for the <BlockCanvas> shell. We mock @xyflow/react so jsdom doesn't
 * choke on ResizeObserver / DOMRect. The mock exposes a minimal surface:
 * <ReactFlow /> renders its children (toolbar etc. live outside it), and
 * `useReactFlow()` returns a stub.
 *
 * The tests verify the wiring: mounting, store interactions via the toolbar,
 * undo/redo round-trip, and that adding/removing blocks updates the canvas.
 */
import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

vi.mock('@xyflow/react', () => {
  const Pass = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ReactFlow: ({ children, nodes, edges }: { children?: React.ReactNode; nodes: unknown[]; edges: unknown[] }) => (
      <div data-testid="rf-mock" data-nodes={String(nodes.length)} data-edges={String(edges.length)}>
        {children}
      </div>
    ),
    ReactFlowProvider: Pass,
    Background: () => <div data-testid="rf-bg" />,
    Controls: () => <div data-testid="rf-controls" />,
    Handle: () => <span />,
    Position: { Left: 'left', Right: 'right' },
    MarkerType: { ArrowClosed: 'arrowclosed' },
    addEdge: () => [],
    applyEdgeChanges: (_: unknown, e: unknown[]) => e,
    applyNodeChanges: (_: unknown, n: unknown[]) => n,
    useReactFlow: () => ({
      screenToFlowPosition: ({ x, y }: { x: number; y: number }) => ({ x, y }),
      fitView: vi.fn(),
    }),
    BaseEdge: () => null,
    EdgeLabelRenderer: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    getBezierPath: () => ['M0 0', 0, 0],
  };
});

vi.mock('@dnd-kit/core', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@dnd-kit/core');
  return {
    ...actual,
    useDroppable: () => ({ setNodeRef: () => undefined, isOver: false }),
  };
});

import { BlockCanvas } from '../BlockCanvas';
import { useBlockCanvasStore } from '../useBlockCanvasStore';

describe('BlockCanvas', () => {
  it('renders the toolbar and the (mocked) flow surface', () => {
    useBlockCanvasStore.getState().reset();
    render(<BlockCanvas />);
    expect(screen.getByTestId('eac-block-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('eac-canvas-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('rf-mock')).toBeInTheDocument();
  });

  it('reflects added blocks in the flow surface (node count)', () => {
    useBlockCanvasStore.getState().reset();
    render(<BlockCanvas />);
    expect(screen.getByTestId('rf-mock')).toHaveAttribute('data-nodes', '0');

    act(() => {
      useBlockCanvasStore.getState().addBlock(
        { kind: 'and', color: 'logic', label: 'AND', payload: { type: 'and' }, position: { x: 0, y: 0 } },
        [],
      );
    });
    expect(screen.getByTestId('rf-mock')).toHaveAttribute('data-nodes', '1');
  });

  it('removes a block when removeBlock is called', () => {
    useBlockCanvasStore.getState().reset();
    const id = useBlockCanvasStore.getState().addBlock(
      { kind: 'and', color: 'logic', label: 'AND', payload: { type: 'and' }, position: { x: 0, y: 0 } },
      [],
    );
    render(<BlockCanvas />);
    expect(screen.getByTestId('rf-mock')).toHaveAttribute('data-nodes', '1');
    act(() => {
      useBlockCanvasStore.getState().removeBlock(id);
    });
    expect(screen.getByTestId('rf-mock')).toHaveAttribute('data-nodes', '0');
  });

  it('undoes and redoes via toolbar buttons', () => {
    useBlockCanvasStore.getState().reset();
    render(<BlockCanvas />);
    act(() => {
      useBlockCanvasStore.getState().addBlock(
        { kind: 'and', color: 'logic', label: 'AND', payload: { type: 'and' }, position: { x: 0, y: 0 } },
        [],
      );
    });
    expect(useBlockCanvasStore.getState().blocks).toHaveLength(1);

    fireEvent.click(screen.getByTestId('eac-canvas-undo'));
    expect(useBlockCanvasStore.getState().blocks).toHaveLength(0);

    fireEvent.click(screen.getByTestId('eac-canvas-redo'));
    expect(useBlockCanvasStore.getState().blocks).toHaveLength(1);
  });

  it('fires onSave with current block/connection counts', () => {
    useBlockCanvasStore.getState().reset();
    const onSave = vi.fn();
    render(<BlockCanvas onSave={onSave} />);
    act(() => {
      useBlockCanvasStore.getState().addBlock(
        { kind: 'and', color: 'logic', label: 'AND', payload: {}, position: { x: 0, y: 0 } },
        [],
      );
    });
    fireEvent.click(screen.getByTestId('eac-canvas-save'));
    expect(onSave).toHaveBeenCalledWith({ blocks: 1, connections: 0 });
  });
});
