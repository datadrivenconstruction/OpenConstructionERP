// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Keyboard reach of the linkable Gantt: the chart is one tab stop however many
 * bars it has, arrow keys rove between bars, and only the active bar's link
 * handles and links join the tab order while focus is inside the chart.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { GanttChart } from './GanttChart';
import type { GanttActivity } from './ganttUtils';
import { useToastStore } from '@/stores/useToastStore';

/** N activities, each linked finish-to-start to the one before it. */
function chain(n: number): GanttActivity[] {
  return Array.from({ length: n }, (_, i) => {
    const start = new Date(Date.UTC(2026, 0, 1 + i * 2));
    const end = new Date(Date.UTC(2026, 0, 2 + i * 2));
    return {
      id: `a${i}`,
      name: `Activity ${i}`,
      start: start.toISOString().slice(0, 10),
      end: end.toISOString().slice(0, 10),
      progress: 0,
      dependencies: i > 0 ? [`a${i - 1}`] : [],
    };
  });
}

/** Everything a Tab press can land on. */
function tabStops(root: ParentNode): Element[] {
  return [
    ...root.querySelectorAll(
      '[tabindex]:not([tabindex^="-"]), button:not([tabindex^="-"]), a[href], input, select, textarea',
    ),
  ];
}

function bar(id: string) {
  return screen.getByTestId(`gantt-bar-${id}`);
}

afterEach(() => {
  cleanup();
  useToastStore.setState({ toasts: [] });
});

describe('GanttChart keyboard reach', () => {
  it('is a single tab stop however many bars it shows', () => {
    for (const n of [5, 120]) {
      const { container, unmount } = render(
        <GanttChart activities={chain(n)} viewMode="day" todayLine={false} onCreateLink={vi.fn()} onDeleteLink={vi.fn()} />,
      );
      const stops = tabStops(container);
      expect(stops).toHaveLength(1);
      expect(stops[0]).toBe(bar('a0'));
      unmount();
    }
  });

  it('adds only the active bar\'s handles and links while focus is in the chart', () => {
    const { container } = render(
      <GanttChart activities={chain(120)} viewMode="day" todayLine={false} onCreateLink={vi.fn()} onDeleteLink={vi.fn()} />,
    );
    act(() => bar('a5').focus());
    expect(document.activeElement).toBe(bar('a5'));
    const stops = tabStops(container).map((el) => el.getAttribute('data-testid'));
    // The bar, its two handles, its incoming and its outgoing link.
    expect(stops.sort()).toEqual(
      [
        'gantt-bar-a5',
        'gantt-link-handle-a5-start',
        'gantt-link-handle-a5-finish',
        'gantt-link-key-a4-a5',
        'gantt-link-key-a5-a6',
      ].sort(),
    );
  });

  it('moves between bars with the arrow keys, Home and End', () => {
    const { container } = render(
      <GanttChart activities={chain(10)} viewMode="day" todayLine={false} onCreateLink={vi.fn()} />,
    );
    act(() => bar('a0').focus());
    fireEvent.keyDown(bar('a0'), { key: 'ArrowDown' });
    expect(document.activeElement).toBe(bar('a1'));
    fireEvent.keyDown(bar('a1'), { key: 'End' });
    expect(document.activeElement).toBe(bar('a9'));
    fireEvent.keyDown(bar('a9'), { key: 'ArrowUp' });
    expect(document.activeElement).toBe(bar('a8'));
    fireEvent.keyDown(bar('a8'), { key: 'Home' });
    expect(document.activeElement).toBe(bar('a0'));
    // Leaving the chart keeps the last bar as the way back in.
    fireEvent.keyDown(bar('a0'), { key: 'ArrowDown' });
    act(() => (document.activeElement as HTMLElement).blur());
    expect(tabStops(container)).toEqual([bar('a1')]);
  });

  it('skips summary rows when roving', () => {
    const acts: GanttActivity[] = [
      { id: 'a', name: 'Alpha', start: '2026-01-05', end: '2026-01-09', progress: 0 },
      { id: 'g', name: 'Group', start: '2026-01-05', end: '2026-01-20', progress: 0, isGroup: true },
      { id: 'b', name: 'Beta', start: '2026-01-15', end: '2026-01-20', progress: 0 },
    ];
    render(<GanttChart activities={acts} viewMode="day" todayLine={false} onCreateLink={vi.fn()} />);
    act(() => bar('a').focus());
    fireEvent.keyDown(bar('a'), { key: 'ArrowDown' });
    expect(document.activeElement).toBe(bar('b'));
  });

  it('opens the activity on Enter, and completes an armed link on Enter', () => {
    const onActivityClick = vi.fn();
    const onCreateLink = vi.fn();
    render(
      <GanttChart
        activities={chain(4)}
        viewMode="day"
        todayLine={false}
        onActivityClick={onActivityClick}
        onCreateLink={onCreateLink}
      />,
    );
    act(() => bar('a0').focus());
    fireEvent.keyDown(bar('a0'), { key: 'Enter' });
    expect(onActivityClick).toHaveBeenCalledWith('a0');

    fireEvent.keyDown(screen.getByTestId('gantt-link-handle-a0-finish'), { key: 'Enter' });
    fireEvent.keyDown(bar('a0'), { key: 'ArrowDown' });
    fireEvent.keyDown(bar('a1'), { key: 'ArrowDown' });
    fireEvent.keyDown(bar('a2'), { key: 'Enter' });
    expect(onCreateLink).toHaveBeenCalledWith('a0', 'a2', 'FS');
    expect(onActivityClick).toHaveBeenCalledTimes(1);
  });

  it('opens a link\'s menu from the keyboard, offers Edit link, and gives focus back to the bar', () => {
    const onActivityClick = vi.fn();
    const onDeleteLink = vi.fn();
    render(
      <GanttChart
        activities={chain(4)}
        viewMode="day"
        todayLine={false}
        onActivityClick={onActivityClick}
        onDeleteLink={onDeleteLink}
      />,
    );
    act(() => bar('a1').focus());
    fireEvent.keyDown(screen.getByTestId('gantt-link-key-a1-a2'), { key: 'Enter' });
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit link' }));
    // The link's type and lag live in the successor's dependency editor.
    expect(onActivityClick).toHaveBeenCalledWith('a2');
    expect(onDeleteLink).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(bar('a1'));

    fireEvent.keyDown(screen.getByTestId('gantt-link-key-a0-a1'), { key: 'Enter' });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(bar('a1'));
  });

  it('has no Edit link without an activity editor to open', () => {
    render(<GanttChart activities={chain(3)} viewMode="day" todayLine={false} onDeleteLink={vi.fn()} />);
    fireEvent.click(screen.getByTestId('gantt-link-hit-a0-a1'));
    expect(screen.getByRole('menuitem', { name: 'Delete link' })).toBeTruthy();
    expect(screen.queryByRole('menuitem', { name: 'Edit link' })).toBeNull();
  });

  it('adds no tab stops at all when linking is off, as before', () => {
    const { container } = render(
      <GanttChart activities={chain(20)} viewMode="day" todayLine={false} onActivityClick={vi.fn()} />,
    );
    expect(tabStops(container)).toHaveLength(0);
    expect(container.querySelector('svg')!.getAttribute('role')).toBe('img');
  });
});
