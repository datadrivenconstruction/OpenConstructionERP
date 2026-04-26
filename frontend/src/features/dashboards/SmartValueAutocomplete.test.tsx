// @ts-nocheck
/**
 * Tests for SmartValueAutocomplete (T03).
 *
 * Covers:
 *   - the internal debounce hook fires once after the delay window,
 *     not on every intermediate keystroke
 *   - keyboard nav: ↓ moves highlight, Enter accepts, Esc closes
 *   - clearing the input fires onClear / onChange('')
 *
 * Network is stubbed via vi.mock on './api'; we drive component
 * timing with `waitFor` rather than fake timers so the async flow
 * (state → effect → fetch → state → render) settles deterministically.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';

vi.mock('./api', () => ({
  getSmartValues: vi.fn(),
}));

import { getSmartValues } from './api';
import {
  SmartValueAutocomplete,
  useDebouncedValue,
} from './SmartValueAutocomplete';

const sampleResponse = {
  snapshot_id: 's1',
  column: 'category',
  query: '',
  items: [
    { value: 'Concrete', count: 400, score: 100 },
    { value: 'ConcretePrecast', count: 150, score: 85 },
    { value: 'Steel', count: 200, score: 0 },
  ],
};

beforeEach(() => {
  (getSmartValues as ReturnType<typeof vi.fn>).mockReset();
  (getSmartValues as ReturnType<typeof vi.fn>).mockResolvedValue(sampleResponse);
});

afterEach(() => {
  cleanup();
});

describe('useDebouncedValue', () => {
  it('only updates after the delay window has elapsed', () => {
    vi.useFakeTimers();
    try {
      const { result, rerender } = renderHook(
        ({ value, delay }) => useDebouncedValue(value, delay),
        { initialProps: { value: 'a', delay: 250 } },
      );
      expect(result.current).toBe('a');

      rerender({ value: 'ab', delay: 250 });
      rerender({ value: 'abc', delay: 250 });

      // Not enough time elapsed — still on the initial value.
      act(() => {
        vi.advanceTimersByTime(100);
      });
      expect(result.current).toBe('a');

      // Cross the threshold — debounced value catches up to the latest.
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(result.current).toBe('abc');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('SmartValueAutocomplete keyboard navigation', () => {
  it('arrow-down moves highlight, Enter accepts', async () => {
    const onChange = vi.fn();
    render(
      <SmartValueAutocomplete
        snapshotId="s1"
        column="category"
        onChange={onChange}
        debounceMs={1}
      />,
    );

    const input = screen.getByTestId('smart-value-input');
    fireEvent.focus(input);

    await waitFor(() => {
      expect(screen.getByTestId('smart-value-listbox')).toBeInTheDocument();
      // Items rendered.
      expect(screen.getByTestId('smart-value-option-1')).toBeInTheDocument();
    });

    // First item highlighted by default (idx=0).
    expect(screen.getByTestId('smart-value-option-0')).toHaveAttribute(
      'aria-selected',
      'true',
    );

    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(screen.getByTestId('smart-value-option-1')).toHaveAttribute(
      'aria-selected',
      'true',
    );

    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('ConcretePrecast');
  });

  it('Escape closes the dropdown', async () => {
    render(
      <SmartValueAutocomplete
        snapshotId="s1"
        column="category"
        debounceMs={1}
      />,
    );

    const input = screen.getByTestId('smart-value-input');
    fireEvent.focus(input);

    await waitFor(() => {
      expect(screen.getByTestId('smart-value-listbox')).toBeInTheDocument();
    });

    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByTestId('smart-value-listbox')).not.toBeInTheDocument();
  });

  it('clears the input via the X button and notifies callbacks', () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    render(
      <SmartValueAutocomplete
        snapshotId="s1"
        column="category"
        value="Concrete"
        onChange={onChange}
        onClear={onClear}
        debounceMs={1}
      />,
    );

    const clear = screen.getByTestId('smart-value-clear');
    fireEvent.click(clear);

    expect(onClear).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('');
  });
});

describe('SmartValueAutocomplete debounced fetching', () => {
  it('only fetches with the final query after the debounce window', async () => {
    const debounce = 60;
    render(
      <SmartValueAutocomplete
        snapshotId="s1"
        column="category"
        debounceMs={debounce}
      />,
    );

    const input = screen.getByTestId('smart-value-input');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'c' } });
    fireEvent.change(input, { target: { value: 'co' } });
    fireEvent.change(input, { target: { value: 'con' } });

    // Wait until the debounced fetch with the final string fires.
    await waitFor(
      () => {
        const calls = (getSmartValues as ReturnType<typeof vi.fn>).mock.calls;
        const last = calls[calls.length - 1];
        expect(last?.[2]).toMatchObject({ query: 'con' });
      },
      { timeout: 1000 },
    );

    // The intermediate strings ('c', 'co') are NOT in the call list:
    // each keystroke restarts the timer, so only the final value
    // makes it through.
    const queries = (getSmartValues as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => c[2]?.query)
      .filter((q) => q !== '' && q !== undefined);
    expect(queries).not.toContain('c');
    expect(queries).not.toContain('co');
    expect(queries).toContain('con');
  });
});
