// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The wall area panel: typing a height reports wall area live, openings are
 * entered as width x height x count, and every value reaches the measurement
 * in canonical metres whatever the reader's unit system.
 */
import { describe, it, expect, vi } from 'vitest';
import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { WallAreaPanel } from '../components/WallAreaPanel';
import type { Measurement } from '../lib/takeoff-types';
import type { MeasurementSystem } from '@/stores/usePreferencesStore';

function mk(partial: Partial<Measurement> = {}): Measurement {
  return {
    id: 'w1',
    type: 'distance',
    points: [],
    value: 12.5,
    unit: 'm',
    label: '',
    annotation: 'Partition',
    page: 1,
    group: 'Walls',
    ...partial,
  };
}

/** Panel wired to real state, the way the properties pane drives it. */
function Harness({
  initial,
  system = 'metric',
  spy,
}: {
  initial: Measurement;
  system?: MeasurementSystem;
  spy?: (m: Measurement) => void;
}) {
  const [m, setM] = useState(initial);
  return (
    <WallAreaPanel
      measurement={m}
      measurementSystem={system}
      onChange={(patch) =>
        setM((prev) => {
          const next = { ...prev, ...patch };
          spy?.(next);
          return next;
        })
      }
    />
  );
}

describe('WallAreaPanel', () => {
  it('asks for a height while the row is a plain length', () => {
    render(<Harness initial={mk()} />);
    expect(screen.getByTestId('wall-height-hint')).toBeInTheDocument();
    expect(screen.queryByTestId('wall-area-formula')).toBeNull();
  });

  it('names every opening input, not only by its placeholder', () => {
    render(<Harness initial={mk({ wallHeight: 2.8 })} />);
    for (const [id, name] of [
      ['wall-opening-width', 'Width'],
      ['wall-opening-height', 'Height'],
      ['wall-opening-count', 'Count'],
    ] as const) {
      const input = screen.getByTestId(id);
      expect(input).toHaveAccessibleName(name);
      expect(input).toHaveAttribute('title', name);
    }
    expect(screen.getByTestId('wall-height-input')).toHaveAccessibleName('Wall height');
  });

  it('shows length x height = area as the height is typed', () => {
    const spy = vi.fn();
    render(<Harness initial={mk()} spy={spy} />);
    fireEvent.change(screen.getByTestId('wall-height-input'), { target: { value: '2,8' } });
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ wallHeight: 2.8 }));
    const formula = screen.getByTestId('wall-area-formula').textContent ?? '';
    expect(formula).toMatch(/12[.,]5/);
    expect(formula).toMatch(/2[.,]8/);
    expect(formula).toMatch(/35/);
    expect(formula).toContain('m²');
  });

  it('adds an opening as width x height x count and nets it out', () => {
    const spy = vi.fn();
    render(<Harness initial={mk({ wallHeight: 2.8 })} spy={spy} />);
    fireEvent.change(screen.getByTestId('wall-opening-width'), { target: { value: '1.2' } });
    fireEvent.change(screen.getByTestId('wall-opening-height'), { target: { value: '1.5' } });
    fireEvent.change(screen.getByTestId('wall-opening-count'), { target: { value: '3' } });
    fireEvent.click(screen.getByTestId('wall-opening-add'));
    expect(spy).toHaveBeenLastCalledWith(
      expect.objectContaining({ openings: [{ width: 1.2, height: 1.5, count: 3 }] }),
    );
    expect(screen.getAllByTestId('wall-opening-row')).toHaveLength(1);
    // 35 - 5.4 = 29.6
    expect(screen.getByTestId('wall-area-net').textContent).toMatch(/29[.,]6/);

    fireEvent.click(screen.getByTestId('wall-opening-remove'));
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ openings: undefined }));
  });

  it('keeps the add button off until width, height and count are valid', () => {
    render(<Harness initial={mk({ wallHeight: 2.8 })} />);
    const add = screen.getByTestId('wall-opening-add') as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    fireEvent.change(screen.getByTestId('wall-opening-width'), { target: { value: '0.9' } });
    expect(add.disabled).toBe(true);
    fireEvent.change(screen.getByTestId('wall-opening-height'), { target: { value: '2.1' } });
    expect(add.disabled).toBe(false);
  });

  it('warns when the openings are larger than the wall', () => {
    render(
      <Harness initial={mk({ value: 2, wallHeight: 2.5, openings: [{ width: 2, height: 2, count: 2 }] })} />,
    );
    expect(screen.getByTestId('wall-openings-exceed')).toBeInTheDocument();
  });

  it('imperial: the height is typed in feet and stored in metres', () => {
    const spy = vi.fn();
    render(<Harness initial={mk({ value: 3.048 })} system="imperial" spy={spy} />);
    fireEvent.change(screen.getByTestId('wall-height-input'), { target: { value: '8' } });
    const last = spy.mock.calls.at(-1)![0] as Measurement;
    expect(last.wallHeight).toBeCloseTo(2.4384, 6);
    const formula = screen.getByTestId('wall-area-formula').textContent ?? '';
    expect(formula).toContain('ft²');
    expect(formula).toMatch(/80/);
  });

  it('clearing the height returns the row to a plain length', () => {
    const spy = vi.fn();
    render(<Harness initial={mk({ wallHeight: 2.8 })} spy={spy} />);
    fireEvent.click(screen.getByTestId('wall-height-reset'));
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ wallHeight: undefined }));
    expect(screen.getByTestId('wall-height-hint')).toBeInTheDocument();
  });
});
