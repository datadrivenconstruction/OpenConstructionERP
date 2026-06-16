import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { takeoffApi, type MeasurementResponse } from '@/features/takeoff/api';
import {
  useMeasurementPersistence,
  getDocumentIndex,
  removeFromStorage,
} from './useMeasurementPersistence';
import { emptyPageScales, type PageScales } from './data/page-scales';

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

const serverMeasurement = (
  overrides: Partial<MeasurementResponse> = {},
): MeasurementResponse => ({
  id: 'server-m1',
  project_id: 'project-a',
  document_id: 'doc-123',
  page: 1,
  type: 'distance',
  group_name: 'General',
  group_color: '#3B82F6',
  annotation: 'Distance m1',
  points: [{ x: 0, y: 0 }, { x: 100, y: 0 }],
  measurement_value: 2.5,
  measurement_unit: 'm',
  depth: null,
  volume: null,
  perimeter: null,
  count_value: null,
  scale_pixels_per_unit: 100,
  linked_boq_position_id: null,
  metadata: { frontend_id: 'm1' },
  created_by: 'user-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

const defaultScale = { pixelsPerUnit: 100, unitLabel: 'm' };
const basePageScales: PageScales = emptyPageScales();

describe('useMeasurementPersistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns empty state when no fileName', () => {
    const setM = vi.fn();
    const setPS = vi.fn();
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: null,
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );
    expect(result.current.hasPersistedData).toBe(false);
    expect(result.current.savedDocumentCount).toBe(0);
  });

  it('saveNow persists measurements + page scales to localStorage', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'test.pdf',
        documentIdentity: 'doc-test',
        measurements: [m1],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );

    act(() => {
      result.current.saveNow();
    });

    // Check localStorage contains the data
    const raw = localStorage.getItem('oe_takeoff_p_local__doc-test');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.measurements).toHaveLength(1);
    expect(parsed.measurements[0].id).toBe('m1');
    // Both the new per-page model and the legacy single scale are written.
    expect(parsed.pageScales.defaultScale.pixelsPerUnit).toBe(100);
    expect(parsed.scale.pixelsPerUnit).toBe(100);
    expect(parsed.savedAt).toBeGreaterThan(0);
  });

  it('migrates a legacy single-scale document into the page-scale default', () => {
    // Pre-populate localStorage in the OLD format (only ``scale``).
    const m1 = makeMeasurement('m1');
    const savedScale = { pixelsPerUnit: 50, unitLabel: 'm' };
    localStorage.setItem(
      'oe_takeoff_p_local__doc-plan',
      JSON.stringify({ measurements: [m1], scale: savedScale, savedAt: Date.now() }),
    );
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['oe_takeoff_p_local__doc-plan']));

    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'plan.pdf',
        documentIdentity: 'doc-plan',
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );

    expect(setM).toHaveBeenCalledWith([m1]);
    // The legacy single scale is promoted to the document default; no page
    // override exists yet so every page reads 50 until re-calibrated.
    const ps = setPS.mock.calls[0]![0] as PageScales;
    expect(ps.defaultScale.pixelsPerUnit).toBe(50);
    expect(ps.byPage).toEqual({});
  });

  it('reads back a new per-page scale document as-is', () => {
    const m1 = makeMeasurement('m1', 3);
    const pageScales: PageScales = {
      defaultScale: { pixelsPerUnit: 100, unitLabel: 'm' },
      byPage: { 3: { pixelsPerUnit: 25, unitLabel: 'm' } },
    };
    localStorage.setItem(
      'oe_takeoff_p_local__doc-multi',
      JSON.stringify({ measurements: [m1], pageScales, scale: defaultScale, savedAt: Date.now() }),
    );
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['oe_takeoff_p_local__doc-multi']));

    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'multi.pdf',
        documentIdentity: 'doc-multi',
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );

    const ps = setPS.mock.calls[0]![0] as PageScales;
    expect(ps.defaultScale.pixelsPerUnit).toBe(100);
    expect(ps.byPage[3]!.pixelsPerUnit).toBe(25);
  });

  it('clearPersisted removes data from localStorage', () => {
    const setM = vi.fn();
    const setPS = vi.fn();
    // Save first
    localStorage.setItem(
      'oe_takeoff_p_local__doc-test',
      JSON.stringify({ measurements: [], scale: defaultScale, savedAt: Date.now() }),
    );
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['oe_takeoff_p_local__doc-test']));

    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'test.pdf',
        documentIdentity: 'doc-test',
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );

    act(() => {
      result.current.clearPersisted();
    });

    expect(localStorage.getItem('oe_takeoff_p_local__doc-test')).toBeNull();
    expect(getDocumentIndex()).not.toContain('oe_takeoff_p_local__doc-test');
  });

  it('getDocumentIndex returns list of saved documents', () => {
    expect(getDocumentIndex()).toEqual([]);

    localStorage.setItem('oe_takeoff_index', JSON.stringify(['a.pdf', 'b.pdf']));
    expect(getDocumentIndex()).toEqual(['a.pdf', 'b.pdf']);
  });

  it('removeFromStorage removes a specific document', () => {
    localStorage.setItem('oe_takeoff_p_local__doc-id', '{}');
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['oe_takeoff_p_local__doc-id', 'other.pdf']));

    removeFromStorage(null, 'doc-id');

    expect(localStorage.getItem('oe_takeoff_p_local__doc-id')).toBeNull();
    expect(getDocumentIndex()).toEqual(['other.pdf']);
  });

  it('auto-saves measurement changes immediately for reload safety', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'auto.pdf',
        documentIdentity: 'doc-auto',
        measurements: [m1],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );

    const raw = localStorage.getItem('oe_takeoff_p_local__doc-auto');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).measurements).toHaveLength(1);
  });

  it('saves drawn measurements before server hydration finishes', () => {
    const list = vi.spyOn(takeoffApi, 'list').mockReturnValue(new Promise<never>(() => {}));
    const m1 = makeMeasurement('m1');

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'pending.pdf',
        documentIdentity: 'doc-pending',
        measurements: [m1],
        setMeasurements: vi.fn(),
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: 'project-a',
      }),
    );

    const raw = localStorage.getItem('oe_takeoff_p_project-a__doc-pending');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).measurements).toHaveLength(1);

    list.mockRestore();
  });

  it('does not overwrite existing local data with an empty pre-hydration state', () => {
    const list = vi.spyOn(takeoffApi, 'list').mockReturnValue(new Promise<never>(() => {}));
    const m1 = makeMeasurement('m1');
    localStorage.setItem(
      'oe_takeoff_p_project-a__doc-pending',
      JSON.stringify({ measurements: [m1], scale: defaultScale, savedAt: Date.now() }),
    );

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'pending.pdf',
        documentIdentity: 'doc-pending',
        measurements: [],
        setMeasurements: vi.fn(),
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: 'project-a',
      }),
    );

    const raw = localStorage.getItem('oe_takeoff_p_project-a__doc-pending');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).measurements).toHaveLength(1);

    list.mockRestore();
  });

  it('hydrates server rows plus unsynced local rows after a partial server sync', async () => {
    const localM1 = makeMeasurement('m1');
    const localM2 = makeMeasurement('m2');
    localStorage.setItem(
      'oe_takeoff_p_project-a__doc-partial',
      JSON.stringify({
        measurements: [localM1, localM2],
        scale: defaultScale,
        pageScales: basePageScales,
        savedAt: Date.now(),
      }),
    );
    const list = vi.spyOn(takeoffApi, 'list').mockResolvedValue([
      serverMeasurement({ document_id: 'doc-partial', points: localM1.points }),
    ]);
    const setM = vi.fn();

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'partial.pdf',
        documentIdentity: 'doc-partial',
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: 'project-a',
      }),
    );

    await waitFor(() => {
      const lastCall = setM.mock.calls.at(-1)?.[0];
      expect(lastCall).toHaveLength(2);
      expect(lastCall.map((m: { id: string }) => m.id)).toEqual(['m1', 'm2']);
      expect(lastCall[0]!.serverId).toBe('server-m1');
      expect(lastCall[1]!.serverId).toBeUndefined();
    });

    list.mockRestore();
  });

  it('discards local measurements that have a serverId but are missing from the server', async () => {
    const localM1 = makeMeasurement('m1');
    const localM2 = { ...makeMeasurement('m2'), serverId: 'server-m2' };
    localStorage.setItem(
      'oe_takeoff_p_project-a__doc-deleted',
      JSON.stringify({
        measurements: [localM1, localM2],
        scale: defaultScale,
        pageScales: basePageScales,
        savedAt: Date.now(),
      }),
    );
    const list = vi.spyOn(takeoffApi, 'list').mockResolvedValue([
      serverMeasurement({ document_id: 'doc-deleted', points: localM1.points }),
    ]);
    const setM = vi.fn();

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'deleted.pdf',
        documentIdentity: 'doc-deleted',
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: 'project-a',
      }),
    );

    await waitFor(() => {
      const lastCall = setM.mock.calls.at(-1)?.[0];
      expect(lastCall).toHaveLength(1);
      expect(lastCall[0]!.id).toBe('m1');
      expect(lastCall[0]!.serverId).toBe('server-m1');
    });

    list.mockRestore();
  });


  it('savedDocumentCount reflects storage index size', () => {
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['a.pdf', 'b.pdf', 'c.pdf']));
    const setM = vi.fn();
    const setPS = vi.fn();

    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: null,
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );

    expect(result.current.savedDocumentCount).toBe(3);
  });

  it('handles corrupt localStorage gracefully', () => {
    localStorage.setItem('oe_takeoff_p_local__doc-bad', '{invalid json');
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['oe_takeoff_p_local__doc-bad']));

    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'bad.pdf',
        documentIdentity: 'doc-bad',
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );

    // Corrupt data is ignored, but the hook still clears any stale in-memory
    // measurements before attempting to hydrate the new document scope.
    expect(setM).toHaveBeenCalledWith([]);
  });

  it('stores stable document identities under project-scoped localStorage keys', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'abc.pdf',
        documentIdentity: 'doc-123',
        measurements: [m1],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: 'project-a',
      }),
    );

    act(() => {
      result.current.saveNow();
    });

    expect(localStorage.getItem('oe_takeoff_p_project-a__doc-123')).toBeTruthy();
    expect(localStorage.getItem('oe_takeoff_abc.pdf')).toBeNull();
  });

  it('persists local-only uploads locally without server-syncing them', async () => {
    vi.useFakeTimers();
    const bulkCreate = vi.spyOn(takeoffApi, 'bulkCreate').mockResolvedValue([]);
    const m1 = makeMeasurement('m1');

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'abc.pdf',
        documentIdentity: null,
        measurements: [m1],
        setMeasurements: vi.fn(),
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: 'project-a',
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });

    expect(localStorage.getItem('oe_takeoff_p_project-a__abc.pdf')).toBeTruthy();
    expect(bulkCreate).not.toHaveBeenCalled();
    vi.useRealTimers();
    bulkCreate.mockRestore();
  });

  it('persists local-only uploads (no stable identity) to localStorage under fileName-keyed slot', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();

    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'abc.pdf',
        documentIdentity: null,
        measurements: [m1],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: 'project-a',
      }),
    );

    act(() => {
      result.current.saveNow();
    });

    expect(localStorage.getItem('oe_takeoff_p_project-a__abc.pdf')).toBeTruthy();
  });

  it('server-syncs new measurements with the stable document identity, not the filename', async () => {
    vi.useFakeTimers();
    const list = vi.spyOn(takeoffApi, 'list').mockResolvedValue([]);
    const bulkCreate = vi.spyOn(takeoffApi, 'bulkCreate').mockResolvedValue([]);
    const m1 = makeMeasurement('m1');

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'abc.pdf',
        documentIdentity: 'doc-123',
        measurements: [m1],
        setMeasurements: vi.fn(),
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: 'project-a',
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(list).toHaveBeenCalledWith('project-a', 'doc-123');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });

    expect(bulkCreate).toHaveBeenCalled();
    expect(bulkCreate.mock.calls[0]![0][0]!.document_id).toBe('doc-123');

    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('does not leak measurements to the new document key on document switch', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();

    const { rerender } = renderHook(
      (props) =>
        useMeasurementPersistence({
          fileName: props.fileName,
          documentIdentity: props.documentIdentity,
          measurements: props.measurements,
          setMeasurements: setM,
          pageScales: basePageScales,
          setPageScales: setPS,
          scale: defaultScale,
          projectId: 'project-a',
        }),
      {
        initialProps: {
          fileName: 'docA.pdf',
          documentIdentity: 'doc-A',
          measurements: [m1],
        },
      },
    );

    expect(localStorage.getItem('oe_takeoff_p_project-a__doc-A')).toBeTruthy();
    expect(localStorage.getItem('oe_takeoff_p_project-a__doc-B')).toBeNull();

    act(() => {
      rerender({
        fileName: 'docB.pdf',
        documentIdentity: 'doc-B',
        measurements: [m1],
      });
    });

    expect(localStorage.getItem('oe_takeoff_p_project-a__doc-B')).toBeNull();
  });

  it('does not send duplicate bulk-create requests for in-flight measurements', async () => {
    vi.useFakeTimers();
    vi.spyOn(takeoffApi, 'list').mockResolvedValue([]);

    let resolveBulkCreate: (val: any) => void = () => {};
    const bulkCreatePromise = new Promise<any[]>((resolve) => {
      resolveBulkCreate = resolve;
    });
    const bulkCreate = vi.spyOn(takeoffApi, 'bulkCreate').mockReturnValue(bulkCreatePromise as any);

    const m1 = makeMeasurement('m1');
    const setM = vi.fn();

    const { rerender } = renderHook(
      (props) =>
        useMeasurementPersistence({
          fileName: 'abc.pdf',
          documentIdentity: 'doc-123',
          measurements: props.measurements,
          setMeasurements: setM,
          pageScales: basePageScales,
          setPageScales: vi.fn(),
          scale: defaultScale,
          projectId: 'project-a',
        }),
      {
        initialProps: {
          measurements: [m1],
        },
      },
    );

    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });

    expect(bulkCreate).toHaveBeenCalledTimes(1);

    const m2 = makeMeasurement('m2');
    act(() => {
      rerender({ measurements: [m1, m2] });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });

    expect(bulkCreate).toHaveBeenCalledTimes(2);
    const secondCall = bulkCreate.mock.calls[1];
    expect(secondCall).toBeDefined();
    expect(secondCall![0]).toHaveLength(1);
    expect(secondCall![0]![0]!.metadata?.frontend_id).toBe('m2');

    resolveBulkCreate([{ id: 'server-m1', metadata: { frontend_id: 'm1' } }]);

    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('sends a PATCH request when a synced measurement is reshaped', async () => {
    vi.useFakeTimers();
    vi.spyOn(takeoffApi, 'list').mockResolvedValue([]);
    const update = vi.spyOn(takeoffApi, 'update').mockResolvedValue({
      id: 'server-m1',
      measurement_value: 5.0,
      metadata: { frontend_id: 'm1' },
    } as any);

    const m1 = { ...makeMeasurement('m1'), serverId: 'server-m1' };
    const setM = vi.fn();

    const { rerender } = renderHook(
      (props) =>
        useMeasurementPersistence({
          fileName: 'abc.pdf',
          documentIdentity: 'doc-123',
          measurements: props.measurements,
          setMeasurements: setM,
          pageScales: basePageScales,
          setPageScales: vi.fn(),
          scale: defaultScale,
          projectId: 'project-a',
        }),
      {
        initialProps: {
          measurements: [m1],
        },
      },
    );

    // Run effect to seed baseline
    await act(async () => {
      await Promise.resolve();
    });

    // Change geometry of m1
    const m1Reshaped = {
      ...m1,
      points: [{ x: 0, y: 0 }, { x: 200, y: 0 }],
      value: 5.0,
    };

    act(() => {
      rerender({ measurements: [m1Reshaped] });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith('server-m1', expect.objectContaining({
      points: m1Reshaped.points,
    }));

    expect(setM).toHaveBeenCalled();
    const lastCall = setM.mock.calls.at(-1)?.[0];
    expect(typeof lastCall).toBe('function');
    const nextState = lastCall([m1Reshaped]);
    expect(nextState[0]).toEqual(expect.objectContaining({
      id: 'm1',
      value: 5.0,
    }));

    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('does not lose concurrently added/edited measurements when a reshape PATCH resolves', async () => {
    vi.useFakeTimers();
    vi.spyOn(takeoffApi, 'list').mockResolvedValue([]);

    let resolveUpdate: (val: any) => void = () => {};
    const updatePromise = new Promise<any>((resolve) => {
      resolveUpdate = resolve;
    });
    const update = vi.spyOn(takeoffApi, 'update').mockReturnValue(updatePromise);

    const m1 = { ...makeMeasurement('m1'), serverId: 'server-m1' };
    const setM = vi.fn();

    const { rerender } = renderHook(
      (props) =>
        useMeasurementPersistence({
          fileName: 'abc.pdf',
          documentIdentity: 'doc-123',
          measurements: props.measurements,
          setMeasurements: setM,
          pageScales: basePageScales,
          setPageScales: vi.fn(),
          scale: defaultScale,
          projectId: 'project-a',
        }),
      {
        initialProps: {
          measurements: [m1] as any[],
        },
      },
    );

    await act(async () => {
      await Promise.resolve();
    });

    // Reshape m1
    const m1Reshaped = {
      ...m1,
      points: [{ x: 0, y: 0 }, { x: 200, y: 0 }],
      value: 5.0,
    };

    act(() => {
      rerender({ measurements: [m1Reshaped] });
    });

    // Advance to fire the patch effect timer, but don't resolve the promise yet
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(update).toHaveBeenCalledTimes(1);

    // Concurrently add a new measurement m2 while the update is in flight
    const m2 = makeMeasurement('m2');
    act(() => {
      rerender({ measurements: [m1Reshaped, m2] });
    });

    // Now resolve the PATCH update
    await act(async () => {
      resolveUpdate({
        id: 'server-m1',
        measurement_value: 5.0,
        metadata: { frontend_id: 'm1' },
      });
      await Promise.resolve();
    });

    // setM should be called with both measurements, updating m1's value but retaining m2
    expect(setM).toHaveBeenCalled();
    const lastCall = setM.mock.calls.at(-1)?.[0];

    // It should be a function (functional updater) because we fixed the stale closure!
    expect(typeof lastCall).toBe('function');

    const nextState = lastCall([m1Reshaped, m2]);
    expect(nextState).toHaveLength(2);
    expect(nextState[0].id).toBe('m1');
    expect(nextState[0].value).toBe(5.0);
    expect(nextState[1].id).toBe('m2'); // m2 is preserved!

    vi.useRealTimers();
    vi.restoreAllMocks();
  });
});
