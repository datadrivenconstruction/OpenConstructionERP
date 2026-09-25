// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { PdfReportOptions } from './pdfReport';

/* ── jsPDF mock ─────────────────────────────────────────────────────────── */

// Mock jsPDF and jspdf-autotable so tests run without a DOM/canvas environment.
// We capture calls to `save` so we can assert the filename.
const mockSave = vi.fn();
const mockText = vi.fn();
const mockRect = vi.fn();
const mockLine = vi.fn();
const mockAddPage = vi.fn();
const mockSetPage = vi.fn();
const mockRoundedRect = vi.fn();
const mockSetFont = vi.fn();
const mockSetFontSize = vi.fn();
const mockSetFillColor = vi.fn();
const mockSetTextColor = vi.fn();
const mockSetDrawColor = vi.fn();
const mockSetLineWidth = vi.fn();
const mockSplitTextToSize = vi.fn((text: string, _maxWidth: number) => [text]);
const mockGetTextWidth = vi.fn(() => 40);
let mockPageNumber = 3;

vi.mock('jspdf', () => {
  // Vitest 4 requires a mock used with `new` to be backed by a real
  // constructor (`function`/`class`), not an arrow returning an object —
  // an arrow factory throws "is not a constructor" at the `new jsPDF(...)`
  // call site. Use a `function` constructor so `new jsPDF(...)` works while
  // still wiring the shared spies onto every instance.
  const jsPDFMock = vi.fn(function (this: Record<string, unknown>) {
    this.internal = {
      pageSize: { getWidth: () => 210, getHeight: () => 297 },
      getNumberOfPages: () => mockPageNumber,
      getCurrentPageInfo: () => ({ pageNumber: mockPageNumber }),
    };
    this.save = mockSave;
    this.text = mockText;
    this.rect = mockRect;
    this.line = mockLine;
    this.addPage = mockAddPage;
    this.setPage = mockSetPage;
    this.roundedRect = mockRoundedRect;
    this.setFont = mockSetFont;
    this.setFontSize = mockSetFontSize;
    this.setFillColor = mockSetFillColor;
    this.setTextColor = mockSetTextColor;
    this.setDrawColor = mockSetDrawColor;
    this.setLineWidth = mockSetLineWidth;
    this.splitTextToSize = mockSplitTextToSize;
    this.getTextWidth = mockGetTextWidth;
    this.setProperties = vi.fn();
    this.lastAutoTable = { finalY: 100 };
  });
  return { default: jsPDFMock };
});

// Capture every autoTable call so a test can inspect the rendered body rows
// (the Qty / Unit Rate / Total cell strings) and assert reconciliation.
const autoTableCalls: Array<{ head?: unknown; body?: string[][] }> = [];

vi.mock('jspdf-autotable', () => ({
  default: vi
    .fn()
    .mockImplementation(
      (
        doc: { lastAutoTable: { finalY: number } },
        opts: { head?: unknown; body?: string[][] },
      ) => {
        autoTableCalls.push({ head: opts?.head, body: opts?.body });
        doc.lastAutoTable = { finalY: 100 };
      },
    ),
}));

/** Parse a locale-formatted number string ("7,580.00" / "115.50") to a float. */
function parseNum(s: string): number {
  return Number(s.replace(/[^0-9.-]/g, ''));
}

/* ── Test fixtures ──────────────────────────────────────────────────────── */

import type { Position } from './api';

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    id: `pos-${Math.random().toString(36).slice(2)}`,
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: '1',
    description: 'Test position',
    unit: 'm2',
    quantity: 10,
    unit_rate: 50,
    total: 500,
    classification: {},
    source: 'manual',
    confidence: null,
    validation_status: 'passed',
    sort_order: 0,
    metadata: {},
    ...overrides,
  };
}

function makeSection(overrides: Partial<Position> = {}): Position {
  return makePosition({
    unit: '',
    quantity: 0,
    unit_rate: 0,
    total: 0,
    ...overrides,
  });
}

function baseOptions(overrides: Partial<PdfReportOptions> = {}): PdfReportOptions {
  const positions = [
    makeSection({ id: 'sec-1', ordinal: '01', description: 'Earthworks' }),
    makePosition({ id: 'pos-1', parent_id: 'sec-1', ordinal: '01.01', description: 'Excavation', unit: 'm3', quantity: 100, unit_rate: 30, total: 3000 }),
    makePosition({ id: 'pos-2', parent_id: 'sec-1', ordinal: '01.02', description: 'Backfill', unit: 'm3', quantity: 50, unit_rate: 20, total: 1000 }),
  ];
  return {
    boqTitle: 'Test BOQ',
    projectName: 'Test Project',
    date: '2026-03-23',
    currency: '€',
    positions,
    markupTotals: [],
    directCost: 4000,
    netTotal: 4000,
    vatRate: 0.19,
    vatAmount: 760,
    grossTotal: 4760,
    locale: 'en-US',
    ...overrides,
  };
}

/* ── Tests ──────────────────────────────────────────────────────────────── */

beforeEach(() => {
  vi.clearAllMocks();
  mockPageNumber = 3;
  autoTableCalls.length = 0;
});

describe('generateBOQPdf', () => {
  it('does not throw with valid data and triggers save', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    expect(() => generateBOQPdf(baseOptions())).not.toThrow();
    expect(mockSave).toHaveBeenCalledOnce();
  });

  it('uses the boqTitle as the filename base (sanitised)', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    generateBOQPdf(baseOptions({ boqTitle: 'My Project / Phase 1' }));
    expect(mockSave).toHaveBeenCalledWith(expect.stringMatching(/^My Project  Phase 1\.pdf$/));
  });

  it('falls back to "BOQ.pdf" when boqTitle is empty', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    generateBOQPdf(baseOptions({ boqTitle: '' }));
    expect(mockSave).toHaveBeenCalledWith('BOQ.pdf');
  });

  it('does not throw with empty positions list', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    expect(() =>
      generateBOQPdf(
        baseOptions({
          positions: [],
          directCost: 0,
          netTotal: 0,
          vatAmount: 0,
          grossTotal: 0,
        }),
      ),
    ).not.toThrow();
    expect(mockSave).toHaveBeenCalledOnce();
  });

  it('renders with multiple markups without throwing', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    const markupTotals = [
      { name: 'Overhead', percentage: 10, amount: 400 },
      { name: 'Profit', percentage: 5, amount: 220 },
      { name: 'Risk Contingency', percentage: 3, amount: 138.6 },
    ];
    const netTotal = 4000 + 400 + 220 + 138.6;
    const vatAmount = netTotal * 0.19;
    expect(() =>
      generateBOQPdf(
        baseOptions({
          markupTotals,
          netTotal,
          vatAmount,
          grossTotal: netTotal + vatAmount,
        }),
      ),
    ).not.toThrow();
    expect(mockSave).toHaveBeenCalledOnce();
  });

  it('wraps a long markups line on the cover inside the page instead of clipping it', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    const markupTotals = [
      { name: 'Site Overhead', percentage: 8, amount: 320 },
      { name: 'Head Office Overhead', percentage: 4, amount: 160 },
      { name: 'Profit', percentage: 5, amount: 200 },
      { name: 'General Liability Insurance', percentage: 1.5, amount: 60 },
    ];
    const joined = 'Site Overhead 8%, Head Office Overhead 4%, Profit 5%, General Liability Insurance 1.5%';
    mockSplitTextToSize.mockImplementation((text: string) =>
      text === joined ? ['Site Overhead 8%, Head Office Overhead 4%,', 'Profit 5%, General Liability Insurance 1.5%'] : [text],
    );
    generateBOQPdf(baseOptions({ markupTotals }));
    mockSplitTextToSize.mockImplementation((text: string) => [text]);

    const split = mockSplitTextToSize.mock.calls.find((c) => c[0] === joined);
    expect(split).toBeDefined();
    // The value column starts at 72 mm on a 210 mm page with a 20 mm margin.
    expect(split![1]).toBeLessThanOrEqual(210 - 20 - 72);
    const drawn = mockText.mock.calls.find((c) => Array.isArray(c[0]) && c[0].join(' ').includes('General Liability Insurance'));
    expect(drawn).toBeDefined();
    // The row after the wrapped value moves down to make room for its second line.
    const markupsY = mockText.mock.calls.find((c) => c[0] === 'Markups')![2];
    const netY = mockText.mock.calls.find((c) => c[0] === 'Net Total')![2];
    expect(netY - markupsY).toBeGreaterThan(10);
  });

  it('adds a page for TOC when there are multiple sections', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    const secA = makeSection({ id: 'sec-a', ordinal: '01', description: 'Section A' });
    const secB = makeSection({ id: 'sec-b', ordinal: '02', description: 'Section B' });
    const childA = makePosition({ id: 'c-a', parent_id: 'sec-a', ordinal: '01.01', description: 'Item A', total: 100 });
    const childB = makePosition({ id: 'c-b', parent_id: 'sec-b', ordinal: '02.01', description: 'Item B', total: 200 });

    generateBOQPdf(
      baseOptions({
        positions: [secA, childA, secB, childB],
        directCost: 300,
        netTotal: 300,
        vatAmount: 57,
        grossTotal: 357,
      }),
    );

    // addPage is called at least twice: once for TOC, once for BOQ tables, once for summary
    expect(mockAddPage).toHaveBeenCalledTimes(3);
    // setPage is called to re-render TOC with correct page numbers
    expect(mockSetPage).toHaveBeenCalledWith(2);
  });

  it('skips TOC page when there is only one section', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    const sec = makeSection({ id: 'sec-1', ordinal: '01', description: 'Only Section' });
    const child = makePosition({ id: 'c-1', parent_id: 'sec-1', ordinal: '01.01', description: 'Item', total: 500 });

    // Reset addPage call history so we can count only calls from this test
    mockAddPage.mockClear();

    generateBOQPdf(
      baseOptions({
        positions: [sec, child],
        directCost: 500,
        netTotal: 500,
        vatAmount: 95,
        grossTotal: 595,
      }),
    );

    // Without a TOC, addPage is called exactly twice:
    //   1) before the BOQ tables page
    //   2) inside renderSummary
    // With a TOC it would be 3 (cover already exists, +TOC +BOQ +Summary).
    expect(mockAddPage).toHaveBeenCalledTimes(2);
  });
});

describe('buildSectionGroups', () => {
  it('returns empty sections and ungrouped for an empty positions list', async () => {
    const { buildSectionGroups } = await import('./pdfReport');
    const result = buildSectionGroups([]);
    expect(result.sections).toHaveLength(0);
    expect(result.ungrouped).toHaveLength(0);
  });

  it('groups children under their parent section', async () => {
    const { buildSectionGroups } = await import('./pdfReport');
    const sec = makeSection({ id: 'sec-1', ordinal: '01', description: 'Foundations' });
    const child1 = makePosition({ id: 'p1', parent_id: 'sec-1', ordinal: '01.01', total: 200 });
    const child2 = makePosition({ id: 'p2', parent_id: 'sec-1', ordinal: '01.02', total: 300 });

    const result = buildSectionGroups([sec, child1, child2]);

    expect(result.sections).toHaveLength(1);
    expect(result.sections[0].description).toBe('Foundations');
    expect(result.sections[0].children).toHaveLength(2);
    expect(result.sections[0].subtotal).toBe(500);
    expect(result.ungrouped).toHaveLength(0);
  });

  it('places parentless non-section positions in ungrouped', async () => {
    const { buildSectionGroups } = await import('./pdfReport');
    const orphan = makePosition({ id: 'orphan', parent_id: null, ordinal: '99', total: 100 });

    const result = buildSectionGroups([orphan]);

    expect(result.sections).toHaveLength(0);
    expect(result.ungrouped).toHaveLength(1);
    expect(result.ungrouped[0].id).toBe('orphan');
  });

  it('handles multiple sections independently', async () => {
    const { buildSectionGroups } = await import('./pdfReport');
    const secA = makeSection({ id: 'sec-a', ordinal: '01', description: 'A' });
    const secB = makeSection({ id: 'sec-b', ordinal: '02', description: 'B' });
    const childA = makePosition({ id: 'ca', parent_id: 'sec-a', total: 100 });
    const childB1 = makePosition({ id: 'cb1', parent_id: 'sec-b', total: 200 });
    const childB2 = makePosition({ id: 'cb2', parent_id: 'sec-b', total: 300 });

    const result = buildSectionGroups([secA, childA, secB, childB1, childB2]);

    expect(result.sections).toHaveLength(2);
    expect(result.sections[0].subtotal).toBe(100);
    expect(result.sections[1].subtotal).toBe(500);
    expect(result.sections[1].children).toHaveLength(2);
  });

  it('excludes section-type positions from ungrouped list', async () => {
    const { buildSectionGroups } = await import('./pdfReport');
    // A lone section with no children
    const sec = makeSection({ id: 'sec-1', ordinal: '01', description: 'Empty section' });

    const result = buildSectionGroups([sec]);

    expect(result.sections).toHaveLength(1);
    // The section itself should NOT appear in ungrouped
    expect(result.ungrouped).toHaveLength(0);
  });
});

describe('imperial unit + reciprocal-rate reconciliation', () => {
  // A single m2 line: 100 m2 @ 50/m2 = 5000. The BOQ-table autoTable body
  // row is [No., Description, Unit, Qty, Unit Rate, Total]. We pin column
  // indices to those positions.
  const COL_UNIT = 2;
  const COL_QTY = 3;
  const COL_RATE = 4;
  const COL_TOTAL = 5;

  function boqTableRows(): string[][] {
    // The BOQ table is the autoTable call whose head is the 6-column BOQ
    // header (the Cost Summary tables have a 2-column head).
    const call = autoTableCalls.find(
      (c) => Array.isArray(c.head) && (c.head as string[][])[0]?.length === 6,
    );
    return call?.body ?? [];
  }

  it('metric: qty * rate reconciles to the (invariant) total', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    generateBOQPdf(
      baseOptions({
        positions: [
          makeSection({ id: 'sec-1', ordinal: '01', description: 'Walls' }),
          makePosition({
            id: 'pos-1',
            parent_id: 'sec-1',
            ordinal: '01.01',
            description: 'Plaster',
            unit: 'm2',
            quantity: 100,
            unit_rate: 50,
            total: 5000,
          }),
        ],
        measurementSystem: 'metric',
      }),
    );

    const row = boqTableRows().find((r) => r[0] === '01.01');
    expect(row).toBeDefined();
    const qty = parseNum(row![COL_QTY]!);
    const rate = parseNum(row![COL_RATE]!);
    const total = parseNum(row![COL_TOTAL]!);
    // Metric passes through unchanged: 100 m2 @ 50 = 5000.
    expect(qty).toBeCloseTo(100, 2);
    expect(rate).toBeCloseTo(50, 2);
    expect(total).toBeCloseTo(5000, 2);
    expect(qty * rate).toBeCloseTo(total, 1);
  });

  it('imperial: qty is converted, rate is restated reciprocally, total is invariant', async () => {
    const { generateBOQPdf } = await import('./pdfReport');
    generateBOQPdf(
      baseOptions({
        positions: [
          makeSection({ id: 'sec-1', ordinal: '01', description: 'Walls' }),
          makePosition({
            id: 'pos-1',
            parent_id: 'sec-1',
            ordinal: '01.01',
            description: 'Plaster',
            unit: 'm2',
            quantity: 100,
            unit_rate: 50,
            total: 5000,
          }),
        ],
        measurementSystem: 'imperial',
      }),
    );

    const row = boqTableRows().find((r) => r[0] === '01.01');
    expect(row).toBeDefined();
    const qty = parseNum(row![COL_QTY]!);
    const rate = parseNum(row![COL_RATE]!);
    const total = parseNum(row![COL_TOTAL]!);

    // Unit label switched to the imperial form.
    expect(row![COL_UNIT]).toContain('ft');
    // 100 m2 -> 1076.39 ft2 (x 10.7639); rate 50/m2 -> ~4.645/ft2. The cell
    // string is rounded to 2 decimals by the formatter, so compare at that
    // precision (4.65).
    expect(qty).toBeCloseTo(1076.39, 1);
    expect(rate).toBeCloseTo(50 / 10.7639, 1);
    // Money total is NEVER converted - still the canonical 5000.
    expect(total).toBeCloseTo(5000, 2);
    // The whole point: the converted line still reconciles. The displayed
    // rate is rounded to 2 decimals, so qty * rate carries up to (qty * 0.01)
    // of rounding error vs the exact total; assert within that envelope.
    expect(Math.abs(qty * rate - total)).toBeLessThanOrEqual(qty * 0.01);
  });
});
