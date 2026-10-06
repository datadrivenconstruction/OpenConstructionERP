// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Drag-to-link on the Gantt bars.
 *
 * A planner links two activities by dragging from a handle on one bar's end to
 * the other bar, instead of picking the predecessor in a form. These tests
 * drive the pointer sequence a mouse or a finger produces and read what the
 * chart hands its consumer.
 *
 * Geometry: jsdom lays nothing out, so the svg's client rect is all zeros and a
 * client coordinate IS an svg coordinate. The body starts below the 48px
 * header, so a point in row N sits at clientY = 48 + N * 40 + 20. At the 'day'
 * zoom a day is 30px, so with the range opening on 1 Jan:
 *   Alpha  5 Jan - 9 Jan   x 120 .. 270   row 0
 *   Beta  15 Jan - 20 Jan  x 420 .. 600   row 1
 *   Gamma 25 Jan - 28 Jan  x 720 .. 840   row 2
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent, cleanup, screen } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { GanttChart } from './GanttChart';
import type { GanttActivity } from './ganttUtils';
import { useToastStore } from '@/stores/useToastStore';

const HEADER = 48;
const rowY = (row: number) => HEADER + row * 40 + 20;

const ACTIVITIES: GanttActivity[] = [
  { id: 'a', name: 'Alpha', start: '2026-01-05', end: '2026-01-09', progress: 0 },
  { id: 'b', name: 'Beta', start: '2026-01-15', end: '2026-01-20', progress: 0 },
  { id: 'c', name: 'Gamma', start: '2026-01-25', end: '2026-01-28', progress: 0, dependencies: ['b'] },
];

type Props = Partial<ComponentProps<typeof GanttChart>>;

function renderChart(props: Props = {}) {
  return render(
    <GanttChart
      activities={ACTIVITIES}
      viewMode="day"
      startDate="2026-01-01"
      endDate="2026-02-28"
      todayLine={false}
      {...props}
    />,
  );
}

function handle(id: string, side: 'start' | 'finish') {
  return screen.getByTestId(`gantt-link-handle-${id}-${side}`);
}

/** Press on a handle, travel to (x, y), release there. */
function dragLink(from: Element, x: number, y: number) {
  fireEvent.pointerDown(from, { pointerId: 1, button: 0, clientX: 0, clientY: 0 });
  fireEvent.pointerMove(document, { pointerId: 1, clientX: x, clientY: y });
  fireEvent.pointerUp(document, { pointerId: 1, clientX: x, clientY: y });
}

afterEach(() => {
  cleanup();
  useToastStore.setState({ toasts: [] });
});

describe('GanttChart drag-to-link', () => {
  it('links the finish of one bar to another bar as finish-to-start', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    dragLink(handle('a', 'finish'), 500, rowY(1));

    expect(onCreateLink).toHaveBeenCalledTimes(1);
    expect(onCreateLink).toHaveBeenCalledWith('a', 'b', 'FS');
  });

  it('gives finish-to-finish when dropped on the target finish handle', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    // Past Beta's right edge (600), inside its finish handle.
    dragLink(handle('a', 'finish'), 614, rowY(1));

    expect(onCreateLink).toHaveBeenCalledWith('a', 'b', 'FF');
  });

  it('gives start-to-start when dragged from the start handle', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    dragLink(handle('a', 'start'), 500, rowY(1));

    expect(onCreateLink).toHaveBeenCalledWith('a', 'b', 'SS');
  });

  it('gives start-to-finish from the start handle onto the target finish handle', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    dragLink(handle('a', 'start'), 614, rowY(1));

    expect(onCreateLink).toHaveBeenCalledWith('a', 'b', 'SF');
  });

  it('ignores a drop on a summary bar', () => {
    const onCreateLink = vi.fn();
    render(
      <GanttChart
        activities={[...ACTIVITIES, { id: 'g', name: 'Phase', start: '2026-01-05', end: '2026-01-28', progress: 0, isGroup: true }]}
        viewMode="day"
        startDate="2026-01-01"
        endDate="2026-02-28"
        todayLine={false}
        onCreateLink={onCreateLink}
      />,
    );

    // Row 3 is the summary bar, spanning x 120 .. 840.
    dragLink(handle('a', 'finish'), 500, rowY(3));

    expect(onCreateLink).not.toHaveBeenCalled();
  });

  it('draws a dashed preview while dragging and removes it after the drop', () => {
    renderChart({ onCreateLink: vi.fn() });

    fireEvent.pointerDown(handle('a', 'finish'), { pointerId: 1, button: 0 });
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 400, clientY: rowY(1) });
    const preview = screen.getByTestId('gantt-link-preview');
    expect(preview.getAttribute('stroke-dasharray')).toBeTruthy();

    fireEvent.pointerUp(document, { pointerId: 1, clientX: 400, clientY: rowY(1) });
    expect(screen.queryByTestId('gantt-link-preview')).toBeNull();
  });

  it('cancels on Escape and creates nothing on the later release', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    fireEvent.pointerDown(handle('a', 'finish'), { pointerId: 1, button: 0 });
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 500, clientY: rowY(1) });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('gantt-link-preview')).toBeNull();
    fireEvent.pointerUp(document, { pointerId: 1, clientX: 500, clientY: rowY(1) });

    expect(onCreateLink).not.toHaveBeenCalled();
  });

  it('cancels when the browser takes the pointer away (pointercancel)', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    fireEvent.pointerDown(handle('a', 'finish'), { pointerId: 1, button: 0 });
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 500, clientY: rowY(1) });
    fireEvent.pointerCancel(document, { pointerId: 1 });
    fireEvent.pointerUp(document, { pointerId: 1, clientX: 500, clientY: rowY(1) });

    expect(onCreateLink).not.toHaveBeenCalled();
  });

  it('does nothing when dropped back on the same bar', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    dragLink(handle('a', 'finish'), 200, rowY(0));

    expect(onCreateLink).not.toHaveBeenCalled();
  });

  it('does nothing when dropped on empty timeline', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    // Row 1 but far right of Beta.
    dragLink(handle('a', 'finish'), 1200, rowY(1));

    expect(onCreateLink).not.toHaveBeenCalled();
  });

  it('refuses a link that already exists and says so', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    // Gamma already depends on Beta.
    dragLink(handle('b', 'finish'), 780, rowY(2));

    expect(onCreateLink).not.toHaveBeenCalled();
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]!.title).toBe('These activities are already linked');
  });

  it('links by keyboard: Enter on a source handle, then Enter on a target handle', () => {
    const onCreateLink = vi.fn();
    renderChart({ onCreateLink });

    fireEvent.keyDown(handle('a', 'finish'), { key: 'Enter' });
    fireEvent.keyDown(handle('b', 'start'), { key: 'Enter' });

    expect(onCreateLink).toHaveBeenCalledWith('a', 'b', 'FS');
  });

  it('renders no handles and no link menu when the props are absent', () => {
    const { container } = renderChart();

    expect(container.querySelector('[data-testid^="gantt-link-handle-"]')).toBeNull();
    expect(container.querySelector('[data-testid^="gantt-link-hit-"]')).toBeNull();
  });

  it('keeps hidden handles out of the pointer path so arrows stay clickable', () => {
    // The handle hit circles cover the ends of every arrow. At rest they must
    // not take the pointer (jsdom does no hit-testing, so read the class that
    // decides it); hovering the bar or a link in progress turns them on.
    renderChart({ onCreateLink: vi.fn(), onDeleteLink: vi.fn() });
    const group = screen.getByTestId('gantt-link-handles-a');
    const classes = () => group.getAttribute('class')!.split(/\s+/);

    expect(classes()).toContain('pointer-events-none');
    expect(classes()).toContain('group-hover/bar:pointer-events-auto');
    expect(classes()).toContain('[@media(hover:none)]:pointer-events-auto');

    fireEvent.keyDown(handle('a', 'finish'), { key: 'Enter' });
    expect(classes()).toContain('pointer-events-auto');
    expect(classes()).not.toContain('pointer-events-none');
  });

  it('gives summary rows no handles', () => {
    const { container } = render(
      <GanttChart
        activities={[...ACTIVITIES, { id: 'g', name: 'Phase', start: '2026-01-05', end: '2026-01-28', progress: 0, isGroup: true }]}
        viewMode="day"
        startDate="2026-01-01"
        endDate="2026-02-28"
        todayLine={false}
        onCreateLink={vi.fn()}
      />,
    );

    expect(container.querySelector('[data-testid^="gantt-link-handle-g-"]')).toBeNull();
    expect(container.querySelector('[data-testid="gantt-link-handle-a-finish"]')).not.toBeNull();
  });
});

describe('GanttChart move and resize next to link handles', () => {
  it('still resizes from the bar edge when link handles are present', () => {
    const onActivityResize = vi.fn();
    const onCreateLink = vi.fn();
    const { container } = renderChart({ onActivityResize, onCreateLink });

    const rightEdge = [...container.querySelectorAll<SVGRectElement>('rect')].find(
      (r) => r.style.cursor === 'ew-resize' && Number(r.getAttribute('x')) > 260 && Number(r.getAttribute('x')) < 280,
    );
    expect(rightEdge, 'right resize handle of Alpha').toBeDefined();

    fireEvent.pointerDown(rightEdge!, { pointerId: 1, button: 0, clientX: 270, clientY: rowY(0) });
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 330, clientY: rowY(0) });
    fireEvent.pointerUp(document, { pointerId: 1, clientX: 330, clientY: rowY(0) });

    expect(onActivityResize).toHaveBeenCalledWith('a', '2026-01-05', '2026-01-11');
    expect(onCreateLink).not.toHaveBeenCalled();
  });

  it('still moves a bar dragged by its body when link handles are present', () => {
    const onActivityDrag = vi.fn();
    const onCreateLink = vi.fn();
    const { container } = renderChart({ onActivityDrag, onCreateLink });

    const body = container.querySelector('g[aria-label^="Alpha"] rect')!;
    fireEvent.pointerDown(body, { pointerId: 1, button: 0, clientX: 150, clientY: rowY(0) });
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 210, clientY: rowY(0) });
    fireEvent.pointerUp(document, { pointerId: 1, clientX: 210, clientY: rowY(0) });

    expect(onActivityDrag).toHaveBeenCalledWith('a', '2026-01-07', '2026-01-11');
    expect(onCreateLink).not.toHaveBeenCalled();
  });

  it('moves a bar with a finger: touch pointers drive the same drag', () => {
    const onActivityDrag = vi.fn();
    const { container } = renderChart({ onActivityDrag });

    const body = container.querySelector<SVGRectElement>('g[aria-label^="Alpha"] rect')!;
    // The browser must not take the gesture for a scroll, or it cancels it.
    expect(body.style.touchAction).toBe('none');

    fireEvent.pointerDown(body, { pointerId: 7, pointerType: 'touch', button: 0, clientX: 150, clientY: rowY(0) });
    fireEvent.pointerMove(document, { pointerId: 7, pointerType: 'touch', clientX: 240, clientY: rowY(0) });
    fireEvent.pointerUp(document, { pointerId: 7, pointerType: 'touch', clientX: 240, clientY: rowY(0) });

    expect(onActivityDrag).toHaveBeenCalledWith('a', '2026-01-08', '2026-01-12');
  });

  it('drops a move when the browser cancels the pointer', () => {
    const onActivityDrag = vi.fn();
    const { container } = renderChart({ onActivityDrag });

    const body = container.querySelector('g[aria-label^="Alpha"] rect')!;
    fireEvent.pointerDown(body, { pointerId: 1, button: 0, clientX: 150, clientY: rowY(0) });
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 210, clientY: rowY(0) });
    fireEvent.pointerCancel(document, { pointerId: 1 });
    fireEvent.pointerUp(document, { pointerId: 1, clientX: 210, clientY: rowY(0) });

    expect(onActivityDrag).not.toHaveBeenCalled();
  });

  it('does not start a move on a right-button press', () => {
    const onActivityDrag = vi.fn();
    const { container } = renderChart({ onActivityDrag });

    const body = container.querySelector('g[aria-label^="Alpha"] rect')!;
    fireEvent.pointerDown(body, { pointerId: 1, button: 2, clientX: 150, clientY: rowY(0) });
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 210, clientY: rowY(0) });
    fireEvent.pointerUp(document, { pointerId: 1, clientX: 210, clientY: rowY(0) });

    expect(onActivityDrag).not.toHaveBeenCalled();
  });

  it('never starts a move or resize from a link handle', () => {
    const onActivityDrag = vi.fn();
    const onActivityResize = vi.fn();
    const onCreateLink = vi.fn();
    renderChart({ onActivityDrag, onActivityResize, onCreateLink });

    const h = handle('a', 'finish');
    fireEvent.pointerDown(h, { pointerId: 1, button: 0, clientX: 285, clientY: rowY(0) });
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 345, clientY: rowY(0) });
    fireEvent.pointerUp(document, { pointerId: 1, clientX: 345, clientY: rowY(0) });

    expect(onActivityDrag).not.toHaveBeenCalled();
    expect(onActivityResize).not.toHaveBeenCalled();
  });
});

describe('GanttChart arrows by link type', () => {
  // Path start and end points, read off the "M x y ... L x y" the chart draws.
  function ends(container: HTMLElement, key: string) {
    const d = container.querySelector(`[data-testid="gantt-arrow-${key}"]`)!.getAttribute('d')!;
    const nums = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
    return { fromX: nums[0], toX: nums[nums.length - 2] };
  }

  function chartWith(type?: 'FS' | 'SS' | 'FF' | 'SF') {
    const acts: GanttActivity[] = [
      ACTIVITIES[0]!,
      { ...ACTIVITIES[1]!, dependencies: ['a'], dependencyTypes: type ? { a: type } : undefined },
    ];
    return render(
      <GanttChart activities={acts} viewMode="day" startDate="2026-01-01" endDate="2026-02-28" todayLine={false} />,
    );
  }

  it('draws finish-to-start when no type is given, as before', () => {
    const { container } = chartWith();
    expect(ends(container, 'a-b')).toEqual({ fromX: 270, toX: 420 });
  });

  it('anchors SS at both starts, FF at both finishes, SF start to finish', () => {
    expect(ends(chartWith('SS').container, 'a-b')).toEqual({ fromX: 120, toX: 420 });
    cleanup();
    expect(ends(chartWith('FF').container, 'a-b')).toEqual({ fromX: 270, toX: 600 });
    cleanup();
    expect(ends(chartWith('SF').container, 'a-b')).toEqual({ fromX: 120, toX: 600 });
  });
});

describe('GanttChart link removal', () => {
  it('opens a menu on a dependency arrow and deletes that link', () => {
    const onDeleteLink = vi.fn();
    renderChart({ onDeleteLink });

    fireEvent.click(screen.getByTestId('gantt-link-hit-b-c'));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete link' }));

    expect(onDeleteLink).toHaveBeenCalledWith('b', 'c');
    expect(screen.queryByRole('menuitem', { name: 'Delete link' })).toBeNull();
  });

  it('closes the link menu on Escape without deleting', () => {
    const onDeleteLink = vi.fn();
    renderChart({ onDeleteLink });

    fireEvent.click(screen.getByTestId('gantt-link-hit-b-c'));
    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('menuitem', { name: 'Delete link' })).toBeNull();
    expect(onDeleteLink).not.toHaveBeenCalled();
  });
});
