// OpenConstructionERP — DataDrivenConstruction (DDC)
// CAD2DATA Pipeline · PDF Takeoff exports — unit tests
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// DDC-CWICR-OE-2026
import { beforeAll, describe, expect, it, vi } from 'vitest';
import type { Measurement } from '../../../features/takeoff/lib/takeoff-types';
import {
  buildExportFilename,
  buildTakeoffPdf,
  buildTakeoffWorkbook,
  EXCEL_COLUMNS,
  selectAnnotatedPages,
  summariseByGroupType,
} from '../../../features/takeoff/lib/takeoff-export';

/**
 * jsdom omits the `canvas` package by default, so `<canvas>.getContext('2d')`
 * returns `null`.  The PDF exporter uses an offscreen canvas to bake
 * annotations — stub a minimal 2D context surface with the methods the
 * renderer touches.  No pixel correctness needed for unit tests; we only
 * care that the exporter wires page-count, page-order and DOM round-tripping.
 */
beforeAll(() => {
  const makeCtxStub = (): Partial<CanvasRenderingContext2D> => ({
    lineWidth: 0,
    font: '',
    strokeStyle: '#000000',
    fillStyle: '#000000',
    globalAlpha: 1,
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    arc: vi.fn(),
    quadraticCurveTo: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    fillText: vi.fn(),
    measureText: () => ({ width: 50 } as TextMetrics),
    setLineDash: vi.fn(),
    setTransform: vi.fn(),
  });
  HTMLCanvasElement.prototype.getContext = function getContext(
    this: HTMLCanvasElement,
    contextId: string,
  ): RenderingContext | null {
    if (contextId === '2d') return makeCtxStub() as unknown as CanvasRenderingContext2D;
    return null;
  } as typeof HTMLCanvasElement.prototype.getContext;
  // A 1×1 JPEG (red pixel) — gives jsPDF a valid bitstream to embed
  // without triggering filesystem fallback.
  const TINY_JPEG_DATA_URL =
    'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AL+AH//Z';
  HTMLCanvasElement.prototype.toDataURL = function toDataURL(): string {
    return TINY_JPEG_DATA_URL;
  };
});

/* ── Fixtures ────────────────────────────────────────────────────── */

const GROUP_COLORS: Readonly<Record<string, string>> = {
  General: '#3B82F6',
  Structural: '#EF4444',
  Electrical: '#F59E0B',
};

const SAMPLE_MEASUREMENTS: Measurement[] = [
  {
    id: 'm1',
    type: 'distance',
    points: [
      { x: 10, y: 10 },
      { x: 110, y: 10 },
    ],
    value: 5.5,
    unit: 'm',
    label: '5.50 m',
    annotation: 'Wall run',
    page: 1,
    group: 'General',
  },
  {
    id: 'm2',
    type: 'distance',
    points: [
      { x: 0, y: 0 },
      { x: 100, y: 100 },
    ],
    value: 2.25,
    unit: 'm',
    label: '2.25 m',
    annotation: 'Door width',
    page: 1,
    group: 'General',
  },
  {
    id: 'm3',
    type: 'area',
    points: [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ],
    value: 12.5,
    unit: 'm²',
    label: '12.50 m²',
    annotation: 'Living room',
    page: 2,
    group: 'Structural',
  },
  // Annotation-only — has no numeric value, should not feed totals.
  {
    id: 'm4',
    type: 'cloud',
    points: [
      { x: 5, y: 5 },
      { x: 95, y: 5 },
      { x: 95, y: 95 },
      { x: 5, y: 95 },
    ],
    value: 0,
    unit: '',
    label: '',
    annotation: 'Revision A',
    page: 3,
    group: 'General',
  },
];

/* ── 1. Filename format ──────────────────────────────────────────── */

describe('buildExportFilename', () => {
  it('produces takeoff-{slug}-{YYYY-MM-DD}.{ext}', () => {
    // Local-time constructor: buildExportFilename formats the user's local
    // date, so a UTC instant here would assert the wrong day on any
    // machine that isn't running in UTC (e.g. midnight UTC is the
    // previous evening in the Americas).
    const date = new Date(2026, 4, 20, 10, 30);
    expect(buildExportFilename('Berlin · Wohnpark Lichtenberg', 'pdf', date)).toBe(
      'takeoff-berlin_wohnpark_lichtenberg-2026-05-20.pdf',
    );
    expect(buildExportFilename('São Paulo / Vila Madalena', 'xlsx', date)).toBe(
      'takeoff-são_paulo_vila_madalena-2026-05-20.xlsx',
    );
  });

  it('falls back to "untitled" on empty project name', () => {
    const date = new Date(2026, 0, 2);
    expect(buildExportFilename('', 'pdf', date)).toBe('takeoff-untitled-2026-01-02.pdf');
    expect(buildExportFilename('   !!!   ', 'xlsx', date)).toBe(
      'takeoff-untitled-2026-01-02.xlsx',
    );
  });
});

/* ── 2. Summary aggregation math ─────────────────────────────────── */

describe('summariseByGroupType', () => {
  it('sums numeric totals per (group, type) and ignores annotations', () => {
    const rows = summariseByGroupType(SAMPLE_MEASUREMENTS, GROUP_COLORS);
    // 1× General/cloud, 1× General/distance pair, 1× Structural/area.
    expect(rows).toHaveLength(3);

    const generalDistance = rows.find((r) => r.group === 'General' && r.type === 'distance');
    expect(generalDistance).toBeDefined();
    expect(generalDistance!.count).toBe(2);
    expect(generalDistance!.total).toBeCloseTo(7.75, 5);
    expect(generalDistance!.unit).toBe('m');
    expect(generalDistance!.color).toBe('#3B82F6');

    const structuralArea = rows.find((r) => r.group === 'Structural' && r.type === 'area');
    expect(structuralArea).toBeDefined();
    expect(structuralArea!.count).toBe(1);
    expect(structuralArea!.total).toBeCloseTo(12.5, 5);

    const generalCloud = rows.find((r) => r.group === 'General' && r.type === 'cloud');
    expect(generalCloud).toBeDefined();
    expect(generalCloud!.count).toBe(1);
    // Annotation types do not contribute to numeric total.
    expect(generalCloud!.total).toBe(0);
  });

  it('orders rows by group then type for deterministic output', () => {
    const rows = summariseByGroupType(SAMPLE_MEASUREMENTS, GROUP_COLORS);
    const order = rows.map((r) => `${r.group}::${r.type}`);
    expect(order).toEqual([
      'General::cloud',
      'General::distance',
      'Structural::area',
    ]);
  });
});

/* ── 3. PDF page selection (count of visible-annotated pages) ────── */

describe('selectAnnotatedPages + buildTakeoffPdf page count', () => {
  it('returns only pages with at least one visible measurement', () => {
    // Hide "General" → only Structural/area on page 2 should remain.
    const hidden = new Set(['General']);
    expect(selectAnnotatedPages(SAMPLE_MEASUREMENTS, hidden)).toEqual([2]);
    // All visible → pages 1, 2, 3.
    expect(selectAnnotatedPages(SAMPLE_MEASUREMENTS, new Set())).toEqual([1, 2, 3]);
  });

  it('produces a PDF with one page per visible-annotated page + 1 summary page', async () => {
    // Mock pdfDoc: 3 native pages, each renders a viewport of 100x100 px.
    const fakePage = {
      getViewport: ({ scale }: { scale: number }) => ({
        width: 100 * scale,
        height: 100 * scale,
      }),
      // Lazily resolve render() — exporter awaits .promise.
      render: () => ({ promise: Promise.resolve() }),
    };
    const fakeDoc = {
      numPages: 3,
      getPage: vi.fn(async () => fakePage),
    } as unknown as import('pdfjs-dist').PDFDocumentProxy;

    const pdf = await buildTakeoffPdf({
      pdfDoc: fakeDoc,
      measurements: SAMPLE_MEASUREMENTS,
      hiddenGroups: new Set(),
      scale: { pixelsPerUnit: 100, unitLabel: 'm' },
      groupColorMap: GROUP_COLORS,
      projectName: 'Test Project',
    });

    // 3 annotated source pages + 1 summary page = 4.
    expect(pdf.getNumberOfPages()).toBe(4);
    expect(fakeDoc.getPage).toHaveBeenCalledTimes(3);
  });
});

/* ── 4. Excel workbook structure ─────────────────────────────────── */

describe('buildTakeoffWorkbook', () => {
  it('emits the documented column layout on the Measurements sheet', async () => {
    const wb = await buildTakeoffWorkbook({
      measurements: SAMPLE_MEASUREMENTS,
      scale: { pixelsPerUnit: 100, unitLabel: 'm' },
      groupColorMap: GROUP_COLORS,
      projectName: 'Test Project',
    });
    const ws = wb.getWorksheet('Measurements');
    expect(ws).toBeDefined();
    const headerRow = ws!.getRow(1).values as unknown as Array<string | undefined>;
    // exceljs row.values is 1-indexed; drop the leading hole.
    const headers = headerRow.slice(1).map((v) => String(v ?? ''));
    expect(headers).toEqual(EXCEL_COLUMNS.map((c) => c.header));
  });

  it('writes a Summary sheet with grand total row matching count semantics', async () => {
    const wb = await buildTakeoffWorkbook({
      measurements: SAMPLE_MEASUREMENTS,
      scale: { pixelsPerUnit: 100, unitLabel: 'm' },
      groupColorMap: GROUP_COLORS,
      projectName: 'Test Project',
    });
    const summary = wb.getWorksheet('Summary');
    expect(summary).toBeDefined();
    // Header row.
    const headers = (summary!.getRow(1).values as unknown as Array<string | undefined>)
      .slice(1)
      .map((v) => String(v ?? ''));
    expect(headers).toEqual(['Group', 'Type', 'Count', 'Total', 'Unit']);

    // Find the TOTAL row.
    let totalRowCount: number | null = null;
    summary!.eachRow((row) => {
      const groupCell = row.getCell(1).value;
      if (groupCell === 'TOTAL') {
        totalRowCount = Number(row.getCell(3).value);
      }
    });
    // 3 buckets: 2× general distance + 1× general cloud + 1× structural area
    // → count = 2 + 1 + 1 = 4.
    expect(totalRowCount).toBe(4);
  });
});
