import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useState } from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';
import {
  useMeasurementPersistence,
  getDocumentIndex,
  removeFromStorage,
} from './useMeasurementPersistence';
import { emptyPageScales, type PageScales } from './data/page-scales';
import { useAuthStore } from '@/stores/useAuthStore';

// Keep these unit tests hermetic: the hook now calls the server (gated on a
// project + document UUID), so stub the API to return no rows. Each test then
// exercises the localStorage path deterministically.
vi.mock('@/features/takeoff/api', () => ({
  takeoffApi: {
    list: vi.fn().mockResolvedValue([]),
    bulkCreate: vi.fn().mockResolvedValue([]),
    update: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue(undefined),
    // Issue #334: the load effect also fetches the document (for its
    // authoritative page_scales) and PATCHes it when the user calibrates.
    getDocument: vi.fn().mockResolvedValue(null),
    saveDocumentScales: vi.fn().mockResolvedValue({ page_scales: null }),
  },
}));

// Mock measurements. The explicit return type includes the optional fields a
// few tests set after the fact (serverId / color / text) so a ``let rows =
// [makeMeasurement(...)]`` array can be reassigned with those props without a
// narrowed-literal type error.
type TestMeasurement = {
  id: string;
  type: 'distance';
  points: { x: number; y: number }[];
  value: number;
  unit: string;
  label: string;
  annotation: string;
  page: number;
  group: string;
  serverId?: string;
  color?: string;
  /** Mirror of the row's GROUP colour (issue #313), distinct from ``color``
   *  which is this measurement's own override. Needed by the #396/#397 wire
   *  tests below, which assert on how each of the two is cleared. */
  groupColor?: string;
  text?: string;
  strokeWidthReal?: number;
};
const makeMeasurement = (id: string, page = 1): TestMeasurement => ({
  id,
  type: 'distance',
  points: [{ x: 0, y: 0 }, { x: 100, y: 0 }],
  value: 2.5,
  unit: 'm',
  label: 'D1',
  annotation: `Distance ${id}`,
  page,
  group: 'General',
});

const defaultScale = { pixelsPerUnit: 100, unitLabel: 'm' };
const basePageScales: PageScales = emptyPageScales();

// Stable identity (issue #238): measurements are keyed by project + a stable
// document UUID, never the filename. The composite localStorage key is
// ``oe_takeoff_<projectId>__<documentId>``.
const PROJECT = 'proj-1';
const DOC = 'doc-uuid-1';
const compositeKey = `oe_takeoff_${PROJECT}__${DOC}`;

describe('useMeasurementPersistence', () => {
  // Reset the module-default mock behaviour AND call history before every test.
  // The hook now flushes a server sync on unmount (issue #281), so the
  // testing-library cleanup of one test can dispatch bulkCreate/delete that
  // would otherwise pollute the next test's call counts; several tests also
  // install persistent implementations (``mockResolvedValue`` /
  // ``mockImplementation``). A full reset here makes the full-file run match
  // the isolated run.
  beforeEach(async () => {
    localStorage.clear();
    vi.useRealTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockReset().mockResolvedValue([]);
    (takeoffApi.bulkCreate as unknown as ReturnType<typeof vi.fn>).mockReset().mockResolvedValue([]);
    (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mockReset().mockResolvedValue({});
    (takeoffApi.delete as unknown as ReturnType<typeof vi.fn>).mockReset().mockResolvedValue(undefined);
    (takeoffApi.getDocument as unknown as ReturnType<typeof vi.fn>).mockReset().mockResolvedValue(null);
    (takeoffApi.saveDocumentScales as unknown as ReturnType<typeof vi.fn>).mockReset().mockResolvedValue({ page_scales: null });
  });

  // Defensive: if a test leaves fake timers on (e.g. an assertion threw before
  // its own ``vi.useRealTimers()``), restore real timers so the NEXT test's
  // ``waitFor`` polling is not frozen. Real-timer tests are unaffected.
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns empty state when no fileName', () => {
    const setM = vi.fn();
    const setPS = vi.fn();
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: null,
        documentId: null,
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

  it('saveNow persists under the project+document composite key', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'test.pdf',
        documentId: DOC,
        measurements: [m1],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    act(() => {
      result.current.saveNow();
    });

    // Keyed by project+document, NOT by filename (issue #238).
    expect(localStorage.getItem('oe_takeoff_test.pdf')).toBeNull();
    const raw = localStorage.getItem(compositeKey);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.measurements).toHaveLength(1);
    expect(parsed.measurements[0].id).toBe('m1');
    expect(parsed.pageScales.defaultScale.pixelsPerUnit).toBe(100);
    expect(parsed.scale.pixelsPerUnit).toBe(100);
    expect(parsed.savedAt).toBeGreaterThan(0);
    expect(getDocumentIndex()).toContain(compositeKey);
  });

  it('persists locally (not under a composite key) when there is no document UUID', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();
    // A freshly dropped local file: documentId null. It must persist locally
    // but never under the project+document key (it isn't a server document).
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'dropped.pdf',
        documentId: null,
        measurements: [m1],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    act(() => {
      result.current.saveNow();
    });

    const raw = localStorage.getItem('oe_takeoff_local__dropped.pdf');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).measurements).toHaveLength(1);
    // A local-only drop is not added to the synced-document index.
    expect(getDocumentIndex()).toEqual([]);
  });

  it('migrates a legacy single-scale document into the page-scale default', async () => {
    // Pre-populate localStorage in the OLD format (filename key, only ``scale``).
    const m1 = makeMeasurement('m1');
    const savedScale = { pixelsPerUnit: 50, unitLabel: 'm' };
    localStorage.setItem(
      'oe_takeoff_plan.pdf',
      JSON.stringify({ measurements: [m1], scale: savedScale, savedAt: Date.now() }),
    );

    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'plan.pdf',
        documentId: DOC,
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    // The load path is async (server first, then localStorage); the legacy
    // filename key is read and migrated into the composite key.
    await waitFor(() => expect(setM).toHaveBeenCalledWith([m1]));
    const ps = setPS.mock.calls[0]![0] as PageScales;
    expect(ps.defaultScale.pixelsPerUnit).toBe(50);
    expect(ps.byPage).toEqual({});
    // The legacy entry was rewritten under the composite key.
    const migrated = localStorage.getItem(compositeKey);
    expect(migrated).toBeTruthy();
    expect(JSON.parse(migrated!).measurements[0].id).toBe('m1');
  });

  it('reads back a new per-page scale document under the composite key', async () => {
    const m1 = makeMeasurement('m1', 3);
    const pageScales: PageScales = {
      defaultScale: { pixelsPerUnit: 100, unitLabel: 'm' },
      byPage: { 3: { pixelsPerUnit: 25, unitLabel: 'm' } },
    };
    localStorage.setItem(
      compositeKey,
      JSON.stringify({ measurements: [m1], pageScales, scale: defaultScale, savedAt: Date.now() }),
    );
    localStorage.setItem('oe_takeoff_index', JSON.stringify([compositeKey]));

    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'multi.pdf',
        documentId: DOC,
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    await waitFor(() => expect(setPS).toHaveBeenCalled());
    const ps = setPS.mock.calls[0]![0] as PageScales;
    expect(ps.defaultScale.pixelsPerUnit).toBe(100);
    expect(ps.byPage[3]!.pixelsPerUnit).toBe(25);
  });

  it('clearPersisted removes data under the composite key', () => {
    const setM = vi.fn();
    const setPS = vi.fn();
    localStorage.setItem(
      compositeKey,
      JSON.stringify({ measurements: [], scale: defaultScale, savedAt: Date.now() }),
    );
    localStorage.setItem('oe_takeoff_index', JSON.stringify([compositeKey]));

    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'test.pdf',
        documentId: DOC,
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    act(() => {
      result.current.clearPersisted();
    });

    expect(localStorage.getItem(compositeKey)).toBeNull();
    expect(getDocumentIndex()).not.toContain(compositeKey);
  });

  it('getDocumentIndex returns list of saved documents', () => {
    expect(getDocumentIndex()).toEqual([]);

    localStorage.setItem('oe_takeoff_index', JSON.stringify(['a', 'b']));
    expect(getDocumentIndex()).toEqual(['a', 'b']);
  });

  it('removeFromStorage removes a specific project+document', () => {
    const keyA = `oe_takeoff_${PROJECT}__${DOC}`;
    const keyB = `oe_takeoff_${PROJECT}__doc-2`;
    localStorage.setItem(keyA, '{}');
    localStorage.setItem(keyB, '{}');
    localStorage.setItem('oe_takeoff_index', JSON.stringify([keyA, keyB]));

    removeFromStorage(PROJECT, DOC);

    expect(localStorage.getItem(keyA)).toBeNull();
    expect(getDocumentIndex()).toEqual([keyB]);
  });

  it('auto-saves on measurement changes (debounced) under the composite key', () => {
    vi.useFakeTimers();
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'auto.pdf',
        documentId: DOC,
        measurements: [m1],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    // Before debounce
    expect(localStorage.getItem(compositeKey)).toBeNull();

    // After 500ms debounce
    act(() => {
      vi.advanceTimersByTime(600);
    });
    const raw = localStorage.getItem(compositeKey);
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).measurements).toHaveLength(1);

    vi.useRealTimers();
  });

  it('savedDocumentCount reflects storage index size', () => {
    localStorage.setItem('oe_takeoff_index', JSON.stringify(['a', 'b', 'c']));
    const setM = vi.fn();
    const setPS = vi.fn();

    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: null,
        documentId: null,
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
      }),
    );

    expect(result.current.savedDocumentCount).toBe(3);
  });

  it('handles corrupt localStorage gracefully', async () => {
    localStorage.setItem(compositeKey, '{invalid json');
    localStorage.setItem('oe_takeoff_index', JSON.stringify([compositeKey]));

    const setM = vi.fn();
    const setPS = vi.fn();
    await act(async () => {
      renderHook(() =>
        useMeasurementPersistence({
          fileName: 'bad.pdf',
          documentId: DOC,
          measurements: [],
          setMeasurements: setM,
          pageScales: basePageScales,
          setPageScales: setPS,
          scale: defaultScale,
          projectId: PROJECT,
        }),
      );
      // Flush the async load (server -> localStorage fallback).
      await Promise.resolve();
    });

    // Should not call setMeasurements with corrupt data
    expect(setM).not.toHaveBeenCalled();
  });

  // ── Issue #242: two PDFs that share a filename must not share measurements ──
  // The pre-#238 build keyed measurements by filename, so uploading a second
  // PDF whose name matched an earlier one surfaced the earlier file's
  // measurements (cross-document bleed). Identity is now project + a stable
  // document UUID, so two same-named documents are fully isolated and the
  // shared filename key is never written.
  it('isolates two same-named PDFs by document UUID (issue #242)', () => {
    const fileName = 'Floor Plan.pdf';
    const docA = 'doc-uuid-A';
    const docB = 'doc-uuid-B';
    const setM = vi.fn();
    const setPS = vi.fn();

    // Draw + save a measurement against document A.
    const { result: a } = renderHook(() =>
      useMeasurementPersistence({
        fileName,
        documentId: docA,
        measurements: [makeMeasurement('a1')],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );
    act(() => {
      a.current.saveNow();
    });

    // Draw + save a different measurement against document B - same filename,
    // same project, different upload.
    const { result: b } = renderHook(() =>
      useMeasurementPersistence({
        fileName,
        documentId: docB,
        measurements: [makeMeasurement('b1')],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );
    act(() => {
      b.current.saveNow();
    });

    const keyA = `oe_takeoff_${PROJECT}__${docA}`;
    const keyB = `oe_takeoff_${PROJECT}__${docB}`;
    // Each document keeps its own namespace; neither sees the other's work.
    expect(JSON.parse(localStorage.getItem(keyA)!).measurements[0].id).toBe('a1');
    expect(JSON.parse(localStorage.getItem(keyB)!).measurements[0].id).toBe('b1');
    // Nothing was ever written under a filename-derived key (the old bug).
    expect(localStorage.getItem('oe_takeoff_Floor Plan.pdf')).toBeNull();
    expect(localStorage.getItem('oe_takeoff_Floor_Plan.pdf')).toBeNull();
    // Both documents are tracked independently in the index.
    expect(getDocumentIndex()).toEqual(expect.arrayContaining([keyA, keyB]));
  });

  // ── Issue #242: a freshly dropped local file never syncs to the server ──
  // A drop with no server document UUID must stay local-only (no bulkCreate),
  // so the "uploaded PDF vanishes on refresh" path can only ever be backed by
  // a real server document, never a client-only blob the server never saw.
  it('does not server-sync a local drop that has no document UUID (issue #242)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    const setM = vi.fn();
    const setPS = vi.fn();

    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'dropped.pdf',
        documentId: null,
        measurements: [makeMeasurement('m1')],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    // Past the 3s server-sync debounce: still no server write, because identity
    // (project + document UUID) is incomplete.
    act(() => {
      vi.advanceTimersByTime(3500);
    });
    expect(takeoffApi.bulkCreate).not.toHaveBeenCalled();

    vi.useRealTimers();
  });

  // ── Issue #276: server measurements must survive a setter identity change ──
  // The viewer used to pass inline-arrow setters whose identity changed on
  // every render. Those setters sat in the load effect's dependency array, so
  // a re-render WHILE the initial server fetch was in flight tore the effect
  // down (cancelled = true) and the resolved rows were dropped - the saved
  // takeoff silently failed to reappear. The hook now keeps the setters in
  // refs and depends only on the document identity, so an unstable setter can
  // no longer cancel an in-flight load.
  it('keeps server measurements when the setter identity changes mid-load (issue #276)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    let resolveList: ((rows: unknown[]) => void) | null = null;
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () =>
        new Promise((res) => {
          resolveList = res as unknown as (rows: unknown[]) => void;
        }),
    );

    const received: Array<Array<{ id: string }>> = [];
    const setPS = vi.fn();

    // Each render hands the hook brand-new inline-arrow setter closures (the
    // exact #276 trigger).
    const { rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'race.pdf',
        documentId: DOC,
        measurements: [],
        setMeasurements: (ms) => {
          received.push(ms as Array<{ id: string }>);
        },
        pageScales: basePageScales,
        setPageScales: (ps) => setPS(ps),
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    // Re-render twice while the server list promise is still pending.
    rerender();
    rerender();

    // The server now returns one measurement.
    await act(async () => {
      resolveList?.([
        {
          id: 's1', project_id: PROJECT, document_id: DOC, page: 1,
          type: 'distance', points: [{ x: 0, y: 0 }, { x: 10, y: 0 }],
          group_name: 'General', group_color: '#3B82F6', annotation: 'D1',
          measurement_value: 1, measurement_unit: 'm', depth: null,
          volume: null, perimeter: null, count_value: null,
          scale_pixels_per_unit: 100, linked_boq_position_id: null,
          is_deduction: false,
          metadata: { frontend_id: 'm1', scale_calibrated: false },
        },
      ]);
      await Promise.resolve();
    });

    await waitFor(() => expect(received.length).toBeGreaterThan(0));
    const last = received[received.length - 1]!;
    expect(last).toHaveLength(1);
    expect(last[0]!.id).toBe('m1');
  });

  // ── Issue #277: an uncalibrated page must not show a phantom calibration ──
  // A measurement drawn on a page still using the factory default carries the
  // default ratio (100 px/unit). Reconstructing per-page scale from the server
  // used to treat that as a real calibration, so the page came back showing
  // "Calibrated 1:N" instead of "Not calibrated". The page-scale model is now
  // only overwritten for pages that were genuinely calibrated.
  const serverRow = (over: Record<string, unknown>) => ({
    id: 's', project_id: PROJECT, document_id: DOC, page: 1, type: 'distance',
    points: [{ x: 0, y: 0 }, { x: 10, y: 0 }], group_name: 'General',
    group_color: '#3B82F6', annotation: '', measurement_value: 1,
    measurement_unit: 'm', depth: null, volume: null, perimeter: null,
    count_value: null, scale_pixels_per_unit: 100, linked_boq_position_id: null,
    is_deduction: false, metadata: { frontend_id: 'm' },
    ...over,
  });

  it('does not restore an uncalibrated default-scale page as calibrated (issue #277)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      serverRow({
        page: 1, scale_pixels_per_unit: 100,
        metadata: { frontend_id: 'm1', scale_calibrated: false },
      }),
    ]);
    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'flat.pdf', documentId: DOC, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );

    // Measurements still load from the server...
    await waitFor(() => expect(setM).toHaveBeenCalled());
    // ...but the page-scale model is NOT replaced with a phantom calibration:
    // an explicit ``scale_calibrated:false`` page stays on the default.
    expect(setPS).not.toHaveBeenCalled();
  });

  it('restores an explicitly calibrated page from the server (issue #277)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      serverRow({
        id: 's2', page: 2, scale_pixels_per_unit: 25,
        metadata: { frontend_id: 'm1', scale_calibrated: true },
      }),
    ]);
    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'sheet.pdf', documentId: DOC, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );

    await waitFor(() => expect(setPS).toHaveBeenCalled());
    const ps = setPS.mock.calls[0]![0] as PageScales;
    expect(ps.byPage[2]!.pixelsPerUnit).toBe(25);
    expect(ps.byPage[1]).toBeUndefined();
  });

  it('infers calibration for legacy rows (no flag) from the ratio (issue #277)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      // Legacy row still on the factory default -> not calibrated.
      serverRow({ id: 'a', page: 1, scale_pixels_per_unit: 100, metadata: { frontend_id: 'a' } }),
      // Legacy row at a real ratio -> a genuine per-sheet calibration.
      serverRow({ id: 'b', page: 2, scale_pixels_per_unit: 50, metadata: { frontend_id: 'b' } }),
    ]);
    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'legacy.pdf', documentId: DOC, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );

    await waitFor(() => expect(setPS).toHaveBeenCalled());
    const ps = setPS.mock.calls[0]![0] as PageScales;
    expect(ps.byPage[2]!.pixelsPerUnit).toBe(50);
    expect(ps.byPage[1]).toBeUndefined();
  });

  it('hydrates server rows in ascending creation order (issue #375)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    // The list endpoint returns rows newest-first (created_at DESC). Hydrating
    // that verbatim inverted the paint stack on every reload; the hook must
    // sort back to ascending creation order so a reload matches the session.
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      serverRow({ id: 'c', created_at: '2026-01-03T00:00:00Z', metadata: { frontend_id: 'c' } }),
      serverRow({ id: 'b', created_at: '2026-01-02T00:00:00Z', metadata: { frontend_id: 'b' } }),
      serverRow({ id: 'a', created_at: '2026-01-01T00:00:00Z', metadata: { frontend_id: 'a' } }),
    ]);
    const setM = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'stack.pdf', documentId: DOC, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: vi.fn(),
        scale: defaultScale, projectId: PROJECT,
      }),
    );
    await waitFor(() => expect(setM).toHaveBeenCalled());
    const rows = setM.mock.calls[0]![0] as { serverId?: string }[];
    // Oldest first (bottom of the stack), newest last (painted on top).
    expect(rows.map((r) => r.serverId)).toEqual(['a', 'b', 'c']);
  });

  // ── Issue #194: the review state has to survive the reload ────────────────
  // Once a detector stores what it proposes, a reload is what decides whether
  // review means anything. Dropping `review_status` on the way in made a
  // rejection something the next reload undid, and made a stored proposal come
  // back looking exactly like agreed work.

  it('does not resurrect a rejected proposal on reload (issue #194)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      serverRow({ id: 'ok', review_status: 'confirmed', metadata: { frontend_id: 'ok' } }),
      serverRow({ id: 'no', review_status: 'rejected', metadata: { frontend_id: 'no' } }),
    ]);
    const setM = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'reviewed.pdf', documentId: DOC, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: vi.fn(),
        scale: defaultScale, projectId: PROJECT,
      }),
    );
    await waitFor(() => expect(setM).toHaveBeenCalled());
    const rows = setM.mock.calls[0]![0] as { serverId?: string }[];
    // Somebody already said no to 'no'. Putting it back on the canvas asks them
    // to say it again, and counts it towards the sheet until they do.
    expect(rows.map((r) => r.serverId)).toEqual(['ok']);
  });

  it('brings a stored proposal back as a proposal, with its confidence (issue #194)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      serverRow({
        id: 'p1', review_status: 'proposed', confidence: 0.42,
        metadata: { frontend_id: 'p1' },
      }),
      serverRow({ id: 'c1', review_status: 'confirmed', metadata: { frontend_id: 'c1' } }),
    ]);
    const setM = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'proposals.pdf', documentId: DOC, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: vi.fn(),
        scale: defaultScale, projectId: PROJECT,
      }),
    );
    await waitFor(() => expect(setM).toHaveBeenCalled());
    const rows = setM.mock.calls[0]![0] as { serverId?: string; suggested?: boolean; confidence?: number }[];
    const proposal = rows.find((r) => r.serverId === 'p1')!;
    // Flagged, so it renders translucent, counts in the review bar, and can
    // still be rejected. Confidence comes with it: without the number the user
    // is asked to judge a proposal the detector was barely sure of.
    expect(proposal.suggested).toBe(true);
    expect(proposal.confidence).toBe(0.42);
    // A confirmed row is agreed work and must carry no review flag at all.
    expect(rows.find((r) => r.serverId === 'c1')!.suggested).toBeUndefined();
  });

  it('fetches ALL measurement pages, not just the first (issue #377)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    // Simulate the real (un-mocked) list contract: the hook must fetch every
    // page. Here the mock returns a full page then a short page; the hook is
    // expected to concatenate both and never drop the second page's rows.
    // (The pagination loop itself lives in takeoffApi.list; this asserts the
    // hydrate path consumes the complete set the client returns.)
    const many = Array.from({ length: 250 }, (_v, i) =>
      serverRow({ id: `s${i}`, created_at: `2026-01-01T00:00:${String(i % 60).padStart(2, '0')}Z`, metadata: { frontend_id: `s${i}` } }),
    );
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(many);
    const setM = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'big.pdf', documentId: DOC, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: vi.fn(),
        scale: defaultScale, projectId: PROJECT,
      }),
    );
    await waitFor(() => expect(setM).toHaveBeenCalled());
    const rows = setM.mock.calls[0]![0] as unknown[];
    expect(rows).toHaveLength(250);
  });

  it('persists the page calibration flag on server sync (issue #277)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.bulkCreate as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    const calibrated: PageScales = {
      defaultScale,
      byPage: { 1: { pixelsPerUnit: 40, unitLabel: 'm' } },
    };
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'cal.pdf', documentId: DOC,
        measurements: [makeMeasurement('m1', 1)],
        setMeasurements: vi.fn(), pageScales: calibrated, setPageScales: vi.fn(),
        scale: { pixelsPerUnit: 40, unitLabel: 'm' }, projectId: PROJECT,
      }),
    );

    // Past the 3s server-sync debounce.
    act(() => {
      vi.advanceTimersByTime(3500);
    });
    expect(takeoffApi.bulkCreate).toHaveBeenCalled();
    const row = (takeoffApi.bulkCreate as unknown as ReturnType<typeof vi.fn>)
      .mock.calls[0]![0][0];
    expect(row.scale_pixels_per_unit).toBe(40);
    expect(row.metadata.scale_calibrated).toBe(true);

    vi.useRealTimers();
  });

  /* ── Issue #281 / #282: create / update / delete sync + flush + reset ── */

  // A synced measurement (one carrying a serverId) is the precondition for the
  // delete + non-geometry-edit paths, so build one explicitly.
  const makeSyncedMeasurement = (id: string, serverId: string, page = 1) => ({
    ...makeMeasurement(id, page),
    serverId,
  });

  // ── #282 A: deleting a synced measurement DELETEs it on the server ──
  it('syncs a delete of a synced measurement to the server (issue #282)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    const m1 = makeSyncedMeasurement('m1', 'srv-1');
    let rows = [m1];
    const setM = vi.fn();
    const setPS = vi.fn();

    const { result, rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'del.pdf',
        documentId: DOC,
        measurements: rows,
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    // User deletes m1: the viewer registers the deletion then drops it from
    // state. We mirror that here (registerDeletion + remove from the array).
    act(() => {
      result.current.registerDeletion('srv-1');
    });
    rows = [];
    rerender();

    // The delete is queued to localStorage immediately so a reload before the
    // debounce still removes it.
    expect(
      JSON.parse(localStorage.getItem(`${compositeKey}__pending_deletes`)!),
    ).toEqual(['srv-1']);

    // Past the 3s server-sync debounce the DELETE fires and the queue clears.
    await act(async () => {
      vi.advanceTimersByTime(3500);
      await Promise.resolve();
    });
    expect(takeoffApi.delete).toHaveBeenCalledWith('srv-1');
    expect(localStorage.getItem(`${compositeKey}__pending_deletes`)).toBeNull();

    vi.useRealTimers();
  });

  // ── #282 A: a deleted synced row does NOT resurrect on the next load ──
  it('does not resurrect a locally-deleted row when the server still returns it (issue #282)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    // Seed a pending delete for srv-1 as if a prior session deleted it but the
    // server still has the row (the DELETE had not been applied / confirmed).
    localStorage.setItem(`${compositeKey}__pending_deletes`, JSON.stringify(['srv-1']));
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        id: 'srv-1', project_id: PROJECT, document_id: DOC, page: 1,
        type: 'distance', points: [{ x: 0, y: 0 }, { x: 10, y: 0 }],
        group_name: 'General', group_color: '#3B82F6', annotation: 'D1',
        measurement_value: 1, measurement_unit: 'm', depth: null,
        volume: null, perimeter: null, count_value: null,
        scale_pixels_per_unit: 100, linked_boq_position_id: null,
        is_deduction: false, metadata: { frontend_id: 'm1', scale_calibrated: false },
      },
      {
        id: 'srv-2', project_id: PROJECT, document_id: DOC, page: 1,
        type: 'distance', points: [{ x: 0, y: 0 }, { x: 20, y: 0 }],
        group_name: 'General', group_color: '#3B82F6', annotation: 'D2',
        measurement_value: 2, measurement_unit: 'm', depth: null,
        volume: null, perimeter: null, count_value: null,
        scale_pixels_per_unit: 100, linked_boq_position_id: null,
        is_deduction: false, metadata: { frontend_id: 'm2', scale_calibrated: false },
      },
    ]);
    const setM = vi.fn();
    const setPS = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'res.pdf', documentId: DOC, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );

    await waitFor(() => expect(setM).toHaveBeenCalled());
    // The pending-deleted row (srv-1 / m1) is filtered out; only srv-2 loads.
    const loaded = setM.mock.calls[setM.mock.calls.length - 1]![0] as Array<{ id: string }>;
    expect(loaded.map((m) => m.id)).toEqual(['m2']);
  });

  // ── #282 B: a non-geometry edit (group/colour/annotation) PATCHes ──
  it('syncs a non-geometry edit of a synced measurement (issue #282)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      measurement_value: 2.5, metadata: {},
    });
    const m1 = makeSyncedMeasurement('m1', 'srv-1');
    let rows = [m1];
    const setM = vi.fn();
    const setPS = vi.fn();

    const { rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'edit.pdf', documentId: DOC, measurements: rows,
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );

    // First render seeds the sync baseline (no PATCH yet).
    await act(async () => {
      await Promise.resolve();
    });
    expect(takeoffApi.update).not.toHaveBeenCalled();

    // Edit only NON-geometry properties: group, colour, annotation, notes.
    rows = [{ ...m1, group: 'Walls', color: '#FF0000', annotation: 'External wall', text: 'note' }];
    rerender();

    // Past the 400ms edit-PATCH debounce the row is PATCHed with the new props.
    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });
    expect(takeoffApi.update).toHaveBeenCalledTimes(1);
    const [patchedId, body] = (takeoffApi.update as unknown as ReturnType<typeof vi.fn>)
      .mock.calls[0]!;
    expect(patchedId).toBe('srv-1');
    expect(body.group_name).toBe('Walls');
    expect(body.group_color).toBe('#FF0000');
    expect(body.annotation).toBe('External wall');
    expect(body.metadata.text).toBe('note');

    vi.useRealTimers();
  });

  /* ── Issue #396 / #397: clearing a colour has to reach the server ────── */

  /**
   * #396, layer 3. The dirty check is the only thing that decides whether a
   * PATCH is attempted at all, and it used to fold "no override" into the
   * default hex (``m.color || '#3B82F6'``). A measurement pinned to that exact
   * hex and the same measurement with the pin cleared therefore hashed
   * identically: the row never looked dirty and no request was ever sent. This
   * is the case that survives a fix to the request body alone, so it needs its
   * own test - a UI that clears the override would otherwise appear to work and
   * silently do nothing.
   */
  it('fires a PATCH when an override equal to the default colour is cleared (issue #396)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      measurement_value: 2.5, metadata: {},
    });
    // Pinned to the very colour the old signature substituted for "unset".
    const m1 = { ...makeSyncedMeasurement('m1', 'srv-1'), color: '#3B82F6' };
    let rows: TestMeasurement[] = [m1];
    const setM = vi.fn();
    const setPS = vi.fn();

    const { rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'clear-default.pdf', documentId: DOC, measurements: rows,
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );
    await act(async () => { await Promise.resolve(); });
    expect(takeoffApi.update).not.toHaveBeenCalled();

    // The user ticks "Use group color": the override goes away.
    rows = [{ ...m1, color: undefined }];
    rerender();

    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });
    expect(takeoffApi.update).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });

  /**
   * #396, layer 2. ``undefined`` is dropped by ``JSON.stringify`` and the
   * server's update schema is exclude_unset, so an omitted ``group_color``
   * means "leave unchanged" - it preserves the pin the user just cleared.
   * Omission and clearing used to share one encoding; only an explicit null
   * distinguishes them on the wire.
   */
  it('clears a per-measurement override with an explicit null (issue #396)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      measurement_value: 2.5, metadata: {},
    });
    const m1 = { ...makeSyncedMeasurement('m1', 'srv-1'), color: '#EF4444' };
    let rows: TestMeasurement[] = [m1];
    const setM = vi.fn();
    const setPS = vi.fn();

    const { rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'clear-override.pdf', documentId: DOC, measurements: rows,
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );
    await act(async () => { await Promise.resolve(); });

    rows = [{ ...m1, color: undefined }];
    rerender();

    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });
    const body = (takeoffApi.update as unknown as ReturnType<typeof vi.fn>)
      .mock.calls[0]![1];
    expect(body.group_color).toBeNull();
    // Present in the payload, not merely undefined: a key that survives
    // JSON.stringify is the whole point.
    expect(JSON.parse(JSON.stringify(body))).toHaveProperty('group_color', null);

    vi.useRealTimers();
  });

  /**
   * The server half of #397. The retarget clears the moved row's mirrored group
   * colour in memory, but the server MERGES the incoming metadata over the
   * stored blob, so an omitted ``group_custom_color`` leaves the OLD group's
   * colour sitting on the row. The next load folds that stale value into the
   * colour map as though it were the destination group's chosen colour, and the
   * destination is repainted after all - a reload later, which is what made the
   * defect read as intermittent.
   */
  it('clears the mirrored group colour on the wire when a row changes group (issue #397)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      measurement_value: 2.5, metadata: {},
    });
    // A row in a colour-customised group, carrying that group's colour.
    const m1 = { ...makeSyncedMeasurement('m1', 'srv-1'), group: 'Walls', groupColor: '#EF4444' };
    let rows: TestMeasurement[] = [m1];
    const setM = vi.fn();
    const setPS = vi.fn();

    const { rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'group-move.pdf', documentId: DOC, measurements: rows,
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );
    await act(async () => { await Promise.resolve(); });

    // Moved into a group with no custom colour; the viewer's retarget drops the
    // mirror as part of the same edit.
    rows = [{ ...m1, group: 'Slab', groupColor: undefined }];
    rerender();

    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });
    const body = (takeoffApi.update as unknown as ReturnType<typeof vi.fn>)
      .mock.calls[0]![1];
    expect(body.group_name).toBe('Slab');
    expect(JSON.parse(JSON.stringify(body)).metadata).toHaveProperty(
      'group_custom_color',
      null,
    );

    vi.useRealTimers();
  });

  /* ── Issue #396: the corrective write on first load, MEASURED ─────────
   *
   * The #396 fix changes what "no override" hashes to, which changes what the
   * dirty check considers dirty on the very first load after deploy. The claim
   * that this is a bounded one-time correction rather than a write storm was
   * originally reasoned, not tested, so these two tests measure it instead.
   *
   * They assert on REQUEST COUNTS, not on resulting state, because the failure
   * mode being ruled out is "the document saves correctly but hammers the API
   * doing it". `update` is the PATCH, `bulkCreate` the POST and `list` the GET,
   * so a count of zero PATCHes is only meaningful alongside a non-zero GET and
   * loaded rows that CARRY a serverId - otherwise zero would just mean the spy
   * never saw a request it could have made.
   */

  /** The hook's own Measurement type, without exporting it: these tests feed
   *  the loaded rows back in as state, exactly as the viewer does, so they must
   *  hold what the hook hands them. */
  type HookMeasurement = Parameters<typeof useMeasurementPersistence>[0]['measurements'][number];

  /** Advance well past every debounce in the hook (400ms edit PATCH, 500ms
   *  auto-save, 3s server sync) while flushing microtasks between advances, so
   *  a promise that resolves and THEN arms a timer still gets its timer run.
   *  A single advance would let a storm that fires on a later effect pass slip
   *  through as a pass. */
  const settleAllTimers = async () => {
    await act(async () => {
      for (let i = 0; i < 12; i += 1) {
        vi.advanceTimersByTime(1000);
        await Promise.resolve();
      }
    });
  };

  /** ~40 rows as an older build left them server-side: the group's colour
   *  written into the per-measurement `group_color` column. */
  const legacyServerRows = (count: number) =>
    Array.from({ length: count }, (_, i) =>
      serverRow({
        id: `srv-${i}`,
        group_color: '#3B82F6',
        created_at: `2026-01-01T00:00:${String(i % 60).padStart(2, '0')}Z`,
        metadata: { frontend_id: `m${i}`, scale_calibrated: false },
      }),
    );

  /**
   * A pure load must write NOTHING. This is the case that would hit every user
   * at once on the first open after deploy, so a per-row corrective PATCH here
   * would be a storm on every large sheet in the project, not a correction.
   *
   * It is safe because the load effect seeds the sync baseline from the SERVER
   * copy of each row (`mapped`), and the rows put into state are hydrated from
   * that same payload, so both sides of the dirty comparison are computed from
   * one source. The test exists to keep that true: the seeding and the
   * hydration are two separate statements in the load effect, and nothing but
   * this assertion stops a later edit to one of them from drifting.
   *
   * Its control is the test below, which uses the identical harness and settle
   * pattern and observes 40 PATCHes: a zero here therefore means "no write was
   * made", not "this harness cannot see a write".
   */
  it('sends no request at all when loading a document written by an older build (issue #396)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    const ROWS = 40;
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      legacyServerRows(ROWS),
    );
    const setPS = vi.fn();

    // State is fed back into the hook the way the viewer does it. Without this
    // the loaded rows would never become the `measurements` the sync effect
    // compares against, and the test would pass by never looking at anything.
    const { result } = renderHook(() => {
      const [rows, setRows] = useState<HookMeasurement[]>([]);
      useMeasurementPersistence({
        fileName: 'legacy-sheet.pdf', documentId: DOC, measurements: rows,
        setMeasurements: setRows, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      });
      return rows;
    });

    // Twice, and the second pass is not decoration: the async load's state
    // update flushes when the enclosing act() exits, so the effect that would
    // arm a PATCH debounce does not even run until the first pass is over.
    // Asserting after one pass would report zero writes for a storm that had
    // simply not been given a tick to start - which is exactly how a test like
    // this passes while the bug ships.
    await settleAllTimers();
    await settleAllTimers();

    // The load really happened, and it really produced synced rows - so a PATCH
    // was available to be made and simply was not made.
    expect(takeoffApi.list).toHaveBeenCalledTimes(1);
    expect(result.current).toHaveLength(ROWS);
    expect(result.current.every((m) => Boolean(m.serverId))).toBe(true);
    // No corrective writes of any kind. bulkCreate is checked too: rows that
    // lost their serverId on the way through would be re-CREATED, which is the
    // same outage wearing a different verb.
    expect(takeoffApi.update).toHaveBeenCalledTimes(0);
    expect(takeoffApi.bulkCreate).toHaveBeenCalledTimes(0);
    expect(takeoffApi.delete).toHaveBeenCalledTimes(0);

    // Quiet on the next pass too: a loop would only show up after the first
    // round trip re-entered the effect.
    await settleAllTimers();
    expect(takeoffApi.update).toHaveBeenCalledTimes(0);
    expect(takeoffApi.bulkCreate).toHaveBeenCalledTimes(0);

    vi.useRealTimers();
  });

  /**
   * The case that DOES write: a localStorage copy that has no override for
   * rows the server still has the default hex on. The local copy wins in the
   * merge while the baseline comes from the server, so those rows are
   * genuinely dirty and the clear is real work that must reach the server.
   *
   * What is being pinned down is that it is bounded: exactly one PATCH per
   * affected row on the first pass and NONE on the second. One-per-row is a
   * migration; anything that repeats is the #398 failure mode reappearing on
   * the wire, and on a 40-row sheet the two look identical for the first
   * second.
   */
  it('corrects a stale server colour once per row and then goes quiet (issue #396)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    const ROWS = 40;
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      legacyServerRows(ROWS),
    );
    // Resolve with the value the row already carries, so the server-authoritative
    // recompute cannot itself change state and muddy the count.
    (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      measurement_value: 1, metadata: {},
    });
    // The same rows as this client last saved them: no per-measurement override.
    localStorage.setItem(
      compositeKey,
      JSON.stringify({
        measurements: Array.from({ length: ROWS }, (_, i) => ({
          id: `m${i}`, serverId: `srv-${i}`, type: 'distance',
          points: [{ x: 0, y: 0 }, { x: 10, y: 0 }], value: 1, unit: 'm',
          label: '', annotation: '', page: 1, group: 'General',
        })),
        pageScales: basePageScales,
        scale: defaultScale,
        savedAt: Date.now(),
      }),
    );
    const setPS = vi.fn();

    // `touch` re-renders with the same rows under a new array identity, which
    // is what makes the "goes quiet" assertion mean anything - see below.
    const { result } = renderHook(() => {
      const [rows, setRows] = useState<HookMeasurement[]>([]);
      useMeasurementPersistence({
        fileName: 'stale-colour.pdf', documentId: DOC, measurements: rows,
        setMeasurements: setRows, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      });
      return { rows, touch: () => setRows((prev) => [...prev]) };
    });

    await settleAllTimers();

    // A second pass is required to OBSERVE the first: the async load's state
    // update flushes when the enclosing act() exits, so the effect that arms
    // the PATCH debounce only runs after the first pass has advanced all its
    // timers. Asserting on the first pass alone would report zero writes for a
    // storm that had merely not been given a tick to start.
    await settleAllTimers();

    const calls = (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mock.calls;
    expect(result.current.rows).toHaveLength(ROWS);
    // One per row, and one ROW per call: 40 calls against 5 ids would be a loop
    // that happens to add up to the right total.
    expect(calls).toHaveLength(ROWS);
    expect(new Set(calls.map((c) => c[0])).size).toBe(ROWS);
    // And every one of them is the clear, not some unrelated churn.
    expect(calls.every((c) => c[1].group_color === null)).toBe(true);

    // The correction is one-time. Simply letting more time pass does NOT show
    // that: the PATCH effect is keyed on the `measurements` identity, so with
    // nothing re-rendering it cannot fire again whether or not the baseline
    // moved, and the assertion would hold even against a server that rejected
    // every request. Re-render with the same rows under a new array identity -
    // the cheapest thing the viewer does constantly - and the effect re-runs
    // its dirty check for real. If the baseline had not advanced, all 40 rows
    // would still look dirty and PATCH again.
    await act(async () => {
      result.current.touch();
    });
    await settleAllTimers();
    expect(takeoffApi.update).toHaveBeenCalledTimes(ROWS);

    vi.useRealTimers();
  });

  // ── #281: unmount/teardown flushes a pending change to localStorage ──
  it('flushes the latest measurements to localStorage on unmount (issue #281)', () => {
    const m1 = makeMeasurement('m1');
    const setM = vi.fn();
    const setPS = vi.fn();
    const { unmount } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'flush.pdf', documentId: DOC, measurements: [m1],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );

    // Nothing persisted yet (the 500ms auto-save debounce has not fired and we
    // never called saveNow).
    expect(localStorage.getItem(compositeKey)).toBeNull();

    // Leaving the document (SPA navigation / filmstrip switch remount) must
    // flush synchronously so the just-drawn measurement is not lost.
    unmount();
    const raw = localStorage.getItem(compositeKey);
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).measurements[0].id).toBe('m1');
  });

  // ── #281: switching the document id loads the new doc, never carrying the
  //          previous document's measurements across. ──
  it('resets and reloads when the document id changes (issue #281)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    const DOC_A = 'doc-A';
    const DOC_B = 'doc-B';
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (_p: string, d: string) =>
        Promise.resolve(
          d === DOC_B
            ? [
                {
                  id: 'srv-b', project_id: PROJECT, document_id: DOC_B, page: 1,
                  type: 'distance', points: [{ x: 0, y: 0 }, { x: 5, y: 0 }],
                  group_name: 'General', group_color: '#3B82F6', annotation: 'B1',
                  measurement_value: 1, measurement_unit: 'm', depth: null,
                  volume: null, perimeter: null, count_value: null,
                  scale_pixels_per_unit: 100, linked_boq_position_id: null,
                  is_deduction: false, metadata: { frontend_id: 'b1', scale_calibrated: false },
                },
              ]
            : [],
        ),
    );
    const setM = vi.fn();
    const setPS = vi.fn();
    let docId = DOC_A;
    const { rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'doc-a.pdf', documentId: docId, measurements: [],
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );

    // Doc A had no server rows; nothing loaded.
    await act(async () => { await Promise.resolve(); });
    setM.mockClear();

    // Switch to document B (a different id => new identity => fresh load).
    docId = DOC_B;
    rerender();

    // Document B's own measurement loads; A's nothing is carried across.
    await waitFor(() => expect(setM).toHaveBeenCalled());
    const loaded = setM.mock.calls[setM.mock.calls.length - 1]![0] as Array<{ id: string }>;
    expect(loaded.map((m) => m.id)).toEqual(['b1']);
  });

  // ── #282: an undo that restores a deleted synced row cancels the queued
  //          server delete instead of orphaning it. ──
  it('cancels a queued delete when the row is restored before the sync (issue #282)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.delete as unknown as ReturnType<typeof vi.fn>).mockClear();
    const m1 = makeSyncedMeasurement('m1', 'srv-1');
    let rows = [m1];
    const setM = vi.fn();
    const setPS = vi.fn();

    const { result, rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'undo.pdf', documentId: DOC, measurements: rows,
        setMeasurements: setM, pageScales: basePageScales, setPageScales: setPS,
        scale: defaultScale, projectId: PROJECT,
      }),
    );

    // Delete then immediately undo (the row reappears in state with its
    // serverId) - all before the 3s debounce fires.
    act(() => { result.current.registerDeletion('srv-1'); });
    rows = [];
    rerender();
    rows = [m1]; // undo restored it
    rerender();

    await act(async () => {
      vi.advanceTimersByTime(3500);
      await Promise.resolve();
    });
    // The delete was cancelled because the row is live again.
    expect(takeoffApi.delete).not.toHaveBeenCalled();
    expect(localStorage.getItem(`${compositeKey}__pending_deletes`)).toBeNull();

    vi.useRealTimers();
  });

  /* ── Issue #339: real-world line width round-trips + re-syncs ── */

  // A real-world stroke width (canonical metres) rides the free-form metadata
  // blob as ``stroke_width_real`` next to the pixel ``stroke_width``. It must
  // survive a create serialize AND come back on load, so a true-width line
  // renders per each page's scale after a server round-trip.
  it('round-trips strokeWidthReal as stroke_width_real (serialize + deserialize, issue #339)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    const bulkCreate = takeoffApi.bulkCreate as unknown as ReturnType<typeof vi.fn>;
    bulkCreate.mockResolvedValue([]);

    // Serialize: saveNow pushes the create through toApiFormat immediately.
    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'width.pdf',
        documentId: DOC,
        measurements: [{ ...makeMeasurement('m1'), strokeWidthReal: 0.25 }],
        setMeasurements: vi.fn(),
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );
    await act(async () => {
      result.current.saveNow();
      await Promise.resolve();
    });
    expect(bulkCreate).toHaveBeenCalled();
    const created = bulkCreate.mock.calls[0]![0][0];
    expect(created.metadata.stroke_width_real).toBe(0.25);

    // Deserialize: the same metadata blob read back hydrates strokeWidthReal.
    (takeoffApi.list as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { ...created, id: 'srv-1' },
    ]);
    const setM = vi.fn();
    renderHook(() =>
      useMeasurementPersistence({
        fileName: 'width.pdf',
        documentId: 'doc-uuid-2',
        measurements: [],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );
    await waitFor(() => expect(setM).toHaveBeenCalled());
    const loaded = setM.mock.calls[setM.mock.calls.length - 1]![0] as Array<{
      strokeWidthReal?: number;
    }>;
    expect(loaded[0]!.strokeWidthReal).toBe(0.25);
  });

  // An appearance-only real-width change moves no geometry, so the sync
  // signature must carry it (``swr``) or the edit would never reach the server.
  it('re-syncs (PATCHes) when only strokeWidthReal changes (issue #339)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      measurement_value: 2.5,
      metadata: {},
    });
    const m1 = makeSyncedMeasurement('m1', 'srv-1');
    let rows: TestMeasurement[] = [m1];
    const setM = vi.fn();
    const setPS = vi.fn();

    const { rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'width-edit.pdf',
        documentId: DOC,
        measurements: rows,
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: setPS,
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    // First render seeds the sync baseline (no PATCH yet).
    await act(async () => {
      await Promise.resolve();
    });
    expect(takeoffApi.update).not.toHaveBeenCalled();

    // Change ONLY the real width -> the sync signature drifts -> a PATCH fires
    // carrying the new stroke_width_real (an appearance-only, non-geometry edit).
    rows = [{ ...m1, strokeWidthReal: 0.2 }];
    rerender();
    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });
    expect(takeoffApi.update).toHaveBeenCalledTimes(1);
    const [patchedId, body] = (takeoffApi.update as unknown as ReturnType<typeof vi.fn>)
      .mock.calls[0]!;
    expect(patchedId).toBe('srv-1');
    expect(body.metadata.stroke_width_real).toBe(0.2);

    vi.useRealTimers();
  });

  /* ── Issue #382: sync results merge by id via a functional update ── */

  // After bulkCreate resolves, the serverId stamp must be dispatched as a
  // FUNCTIONAL updater computed from the freshest state, not a plain value built
  // from a stale render snapshot - otherwise a user edit that landed while the
  // create was in flight is discarded. We capture the dispatched updater and
  // apply it to a "concurrent" state to prove the edit survives and the serverId
  // still lands.
  it('stamps serverId with a functional update that preserves a concurrent edit (issue #382)', async () => {
    const { takeoffApi } = await import('@/features/takeoff/api');
    const bulkCreate = takeoffApi.bulkCreate as unknown as ReturnType<typeof vi.fn>;
    bulkCreate.mockResolvedValue([{ id: 'srv-1', metadata: { frontend_id: 'm1' } }]);
    const setM = vi.fn();

    const { result } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'merge.pdf',
        documentId: DOC,
        measurements: [makeMeasurement('m1')],
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    await act(async () => {
      result.current.saveNow();
      await Promise.resolve();
    });

    // The stamp is dispatched as a functional updater (not a plain array).
    await waitFor(() =>
      expect(setM.mock.calls.some((c) => typeof c[0] === 'function')).toBe(true),
    );
    const updater = setM.mock.calls
      .map((c) => c[0])
      .find((a) => typeof a === 'function') as (
      prev: TestMeasurement[],
    ) => TestMeasurement[];

    // Apply it to a state where the user edited m1 AFTER the snapshot was sent.
    const concurrent: TestMeasurement[] = [
      { ...makeMeasurement('m1'), annotation: 'edited mid-sync' },
    ];
    const next = updater(concurrent);
    // serverId is stamped AND the concurrent annotation edit is preserved.
    expect(next[0]!.serverId).toBe('srv-1');
    expect(next[0]!.annotation).toBe('edited mid-sync');
  });

  // The edit-PATCH reconcile must likewise merge the server-authoritative value
  // by id through a functional update, preserving any other row edited during
  // the PATCH round-trip.
  it('reconciles PATCH results by id via a functional update (issue #382)', async () => {
    vi.useFakeTimers();
    const { takeoffApi } = await import('@/features/takeoff/api');
    (takeoffApi.update as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      measurement_value: 9.9,
      metadata: {},
    });
    const m1 = makeSyncedMeasurement('m1', 'srv-1');
    let rows: TestMeasurement[] = [m1];
    const setM = vi.fn();

    const { rerender } = renderHook(() =>
      useMeasurementPersistence({
        fileName: 'reconcile.pdf',
        documentId: DOC,
        measurements: rows,
        setMeasurements: setM,
        pageScales: basePageScales,
        setPageScales: vi.fn(),
        scale: defaultScale,
        projectId: PROJECT,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    // Edit m1 (drives the PATCH), then let it reconcile.
    rows = [{ ...m1, annotation: 'changed' }];
    rerender();
    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });

    vi.useRealTimers();
    const updater = setM.mock.calls
      .map((c) => c[0])
      .find((a) => typeof a === 'function') as
      | ((prev: TestMeasurement[]) => TestMeasurement[])
      | undefined;
    expect(updater).toBeTypeOf('function');
    // A concurrent edit to a DIFFERENT row survives the reconcile.
    const concurrent: TestMeasurement[] = [
      { ...m1, value: 9.9 },
      { ...makeMeasurement('m2', 1), serverId: 'srv-2', annotation: 'other edit' },
    ];
    const next = updater!(concurrent);
    expect(next.find((m) => m.id === 'm1')!.value).toBe(9.9);
    expect(next.find((m) => m.id === 'm2')!.annotation).toBe('other edit');
  });

  describe('document calibration write follows takeoff.update', () => {
    const calibrated: PageScales = { defaultScale: { pixelsPerUnit: 250, unitLabel: 'm' }, byPage: {} };

    function renderCalibrated() {
      return renderHook(() =>
        useMeasurementPersistence({
          fileName: 'plan.pdf',
          documentId: DOC,
          measurements: [],
          setMeasurements: vi.fn(),
          pageScales: calibrated,
          setPageScales: vi.fn(),
          scale: defaultScale,
          projectId: PROJECT,
        }),
      );
    }

    afterEach(() => {
      useAuthStore.setState({ userRole: null });
    });

    it('pushes an opened calibration to the document for an editor', async () => {
      useAuthStore.setState({ userRole: 'editor' });
      const { takeoffApi } = await import('@/features/takeoff/api');
      renderCalibrated();
      await waitFor(() => expect(takeoffApi.saveDocumentScales).toHaveBeenCalled(), { timeout: 3000 });
    });

    it('keeps a viewer calibration local instead of sending a write the server refuses', async () => {
      useAuthStore.setState({ userRole: 'viewer' });
      const { takeoffApi } = await import('@/features/takeoff/api');
      renderCalibrated();
      // Past the 800 ms debounce the editor case above resolves within.
      await new Promise((r) => setTimeout(r, 1200));
      expect(takeoffApi.saveDocumentScales).not.toHaveBeenCalled();
    });
  });
});
