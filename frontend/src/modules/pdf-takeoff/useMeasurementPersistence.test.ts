import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import {
  useMeasurementPersistence,
  getDocumentIndex,
  removeFromStorage,
} from './useMeasurementPersistence';

// Mock measurements
const makeMeasurement = (id: string, page = 1) => ({
  id,
  type: 'distance' as const,
  points: [{ x: 0, y: 0 }, { x: 100, y: 0 }],
  value: 2.5,
  unit: 'm',
  label: 'D1',
  annotation: `Distance ${id}`,
  page,
  group: 'General',
});

const defaultScale = { pixelsPerUnit: 100, unitLabel: 'm' };

describe('useMeasurementPersistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns empty state when no fileName', () => {
    const setM = vi.fn();
    const setS = vi.fn();
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: null,
        measurements: [],
        setMeasurements: setM,
        scale: defaultScale,
        setScale: setS,
      }),
    );
    expect(result.current.hasPersistedData).toBe(false);
    expect(result.current.savedDocumentCount).toBe(0);
  });

  it('saveNow persists measurements to localStorage', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setS = vi.fn();
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'test.pdf',
        measurements: [m1],
        setMeasurements: setM,
        scale: defaultScale,
        setScale: setS,
      }),
    );

    act(() => {
      result.current.saveNow();
    });

    // Check localStorage contains the data
    const raw = localStorage.getItem('oe_takeoff_test.pdf');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.measurements).toHaveLength(1);
    expect(parsed.measurements[0].id).toBe('m1');
    expect(parsed.scale.pixelsPerUnit).toBe(100);
    expect(parsed.savedAt).toBeGreaterThan(0);
  });

  it('loads persisted data when fileName changes', () => {
    // Pre-populate localStorage
    const m1 = makeMeasurement('m1');
    const savedScale = { pixelsPerUnit: 50, unitLabel: 'ft' };
    localStorage.setItem(
      'oe_takeoff_plan.pdf',
      JSON.stringify({ measurements: [m1], scale: savedScale, savedAt: Date.now() }),
    );
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['plan.pdf']));

    const setM = vi.fn();
    const setS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'plan.pdf',
        measurements: [],
        setMeasurements: setM,
        scale: defaultScale,
        setScale: setS,
      }),
    );

    expect(setM).toHaveBeenCalledWith([m1]);
    expect(setS).toHaveBeenCalledWith(savedScale);
  });

  it('clearPersisted removes data from localStorage', () => {
    const setM = vi.fn();
    const setS = vi.fn();
    // Save first
    localStorage.setItem(
      'oe_takeoff_test.pdf',
      JSON.stringify({ measurements: [], scale: defaultScale, savedAt: Date.now() }),
    );
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['test.pdf']));

    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'test.pdf',
        measurements: [],
        setMeasurements: setM,
        scale: defaultScale,
        setScale: setS,
      }),
    );

    act(() => {
      result.current.clearPersisted();
    });

    expect(localStorage.getItem('oe_takeoff_test.pdf')).toBeNull();
    expect(getDocumentIndex()).not.toContain('test.pdf');
  });

  it('getDocumentIndex returns list of saved documents', () => {
    expect(getDocumentIndex()).toEqual([]);

    localStorage.setItem('oe_takeoff_index', JSON.stringify(['a.pdf', 'b.pdf']));
    expect(getDocumentIndex()).toEqual(['a.pdf', 'b.pdf']);
  });

  it('removeFromStorage removes a specific document', () => {
    localStorage.setItem('oe_takeoff_doc.pdf', '{}');
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['doc.pdf', 'other.pdf']));

    removeFromStorage('doc.pdf');

    expect(localStorage.getItem('oe_takeoff_doc.pdf')).toBeNull();
    expect(getDocumentIndex()).toEqual(['other.pdf']);
  });

  it('auto-saves on measurement changes (debounced)', async () => {
    vi.useFakeTimers();
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setS = vi.fn();

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'auto.pdf',
        measurements: [m1],
        setMeasurements: setM,
        scale: defaultScale,
        setScale: setS,
      }),
    );

    // Before debounce
    expect(localStorage.getItem('oe_takeoff_auto.pdf')).toBeNull();

    // After 500ms debounce
    vi.advanceTimersByTime(600);
    const raw = localStorage.getItem('oe_takeoff_auto.pdf');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).measurements).toHaveLength(1);

    vi.useRealTimers();
  });

  it('savedDocumentCount reflects storage index size', () => {
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['a.pdf', 'b.pdf', 'c.pdf']));
    const setM = vi.fn();
    const setS = vi.fn();

    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: null,
        measurements: [],
        setMeasurements: setM,
        scale: defaultScale,
        setScale: setS,
      }),
    );

    expect(result.current.savedDocumentCount).toBe(3);
  });

  it('handles corrupt localStorage gracefully', () => {
    localStorage.setItem('oe_takeoff_bad.pdf', '{invalid json');
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['bad.pdf']));

    const setM = vi.fn();
    const setS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'bad.pdf',
        measurements: [],
        setMeasurements: setM,
        scale: defaultScale,
        setScale: setS,
      }),
    );

    // Should not call setMeasurements with corrupt data
    expect(setM).not.toHaveBeenCalled();
  });
});
