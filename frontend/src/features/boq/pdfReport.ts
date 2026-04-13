import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import {
  groupPositionsIntoSections,
  isSection,
  type Position,
} from './api';

/* ── Types ──────────────────────────────────────────────────────────────── */

export interface PdfMarkupTotal {
  name: string;
  percentage: number;
  amount: number;
}

export interface PdfReportOptions {
  /** BOQ title shown in the report header. */
  boqTitle: string;
  /** Optional project name shown on the cover page. */
  projectName?: string;
  /** Optional date string (ISO or display); defaults to today. */
  date?: string;
  /** Currency symbol prepended in display (e.g. "€", "$"). */
  currency: string;
  /** Flat list of all BOQ positions (sections + items). */
  positions: Position[];
  /** Applied markups with pre-computed amounts. */
  markupTotals: PdfMarkupTotal[];
  /** Direct cost (sum of all line-item totals). */
  directCost: number;
  /** Net total after markups. */
  netTotal: number;
  /** VAT rate as decimal (e.g. 0.19 for 19%). */
  vatRate: number;
  /** VAT amount (pre-computed). */
  vatAmount: number;
  /** Gross total including VAT (pre-computed). */
  grossTotal: number;
  /** BCP-47 locale tag for number formatting (e.g. "en-US", "de-DE"). */
  locale?: string;
}

/* ── Internal section data ──────────────────────────────────────────────── */

interface SectionEntry {
  ordinal: string;
  description: string;
  subtotal: number;
  pageNumber: number; // filled after rendering
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

/**
 * Groups a flat positions array into sections with their children and
 * computes per-section subtotals. Also returns any ungrouped line items.
 * This is a pure function and is exported for unit testing.
 */
export function buildSectionGroups(positions: Position[]): {
  sections: Array<{ ordinal: string; description: string; children: Position[]; subtotal: number }>;
  ungrouped: Position[];
} {
  const grouped = groupPositionsIntoSections(positions);
  return {
    sections: grouped.sections.map((g) => ({
      ordinal: g.section.ordinal,
      description: g.section.description,
      children: g.children,
      subtotal: g.subtotal,
    })),
    ungrouped: grouped.ungrouped.filter((p) => !isSection(p)),
  };
}

/** Format a number with currency symbol and locale-aware separators. */
function formatCurrency(value: number, currency: string, locale: string): string {
  try {
    const formatted = new Intl.NumberFormat(locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
    return `${currency}${formatted}`;
  } catch {
    return `${currency}${value.toFixed(2)}`;
  }
}

/** Format a plain number (for quantities). */
function formatNumber(value: number, locale: string): string {
  try {
    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return value.toFixed(2);
  }
}

/** Format a date string or Date to a human-readable display string. */
function formatDate(dateInput: string | undefined, locale: string): string {
  const d = dateInput ? new Date(dateInput) : new Date();
  if (isNaN(d.getTime())) return dateInput ?? '';
  try {
    return d.toLocaleDateString(locale, { year: 'numeric', month: 'long', day: 'numeric' });
  } catch {
    return d.toISOString().split('T')[0] ?? '';
  }
}

/* ── Brand colours ──────────────────────────────────────────────────────── */

const BRAND_DARK = [15, 23, 42] as [number, number, number];     // slate-900
const BRAND_MID = [71, 85, 105] as [number, number, number];     // slate-600
const BRAND_LIGHT = [226, 232, 240] as [number, number, number]; // slate-200
const BRAND_ACCENT = [99, 102, 241] as [number, number, number]; // indigo-500
const WHITE = [255, 255, 255] as [number, number, number];

/* ── Cover page ─────────────────────────────────────────────────────────── */

function renderCoverPage(
  doc: jsPDF,
  options: PdfReportOptions,
  locale: string,
): void {
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();

  // Background header block
  doc.setFillColor(...BRAND_DARK);
  doc.rect(0, 0, pageW, 80, 'F');

  // Accent stripe
  doc.setFillColor(...BRAND_ACCENT);
  doc.rect(0, 78, pageW, 3, 'F');

  // Wordmark
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(11);
  doc.setTextColor(...WHITE);
  doc.text('OpenConstructionERP', 20, 20);

  // BOQ title
  doc.setFontSize(26);
  doc.setFont('helvetica', 'bold');
  const titleLines = doc.splitTextToSize(options.boqTitle, pageW - 40) as string[];
  doc.text(titleLines, 20, 45);

  // Project name
  if (options.projectName) {
    doc.setFontSize(13);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(...BRAND_LIGHT);
    doc.text(options.projectName, 20, 68);
  }

  // ── Meta block below header ───────────────────────────────────────────
  doc.setTextColor(...BRAND_DARK);

  const itemCount = options.positions.filter((p) => !isSection(p)).length;
  const sectionCount = buildSectionGroups(options.positions).sections.length;
  const resourceCount = options.positions.reduce((sum, p) => {
    const meta = p.metadata ?? (p as unknown as Record<string, unknown>).metadata_;
    const res = meta && Array.isArray((meta as Record<string, unknown>).resources)
      ? ((meta as Record<string, unknown>).resources as unknown[]).length : 0;
    return sum + res;
  }, 0);

  const metaY = 96;
  const labelX = 20;
  const valueX = 72;

  // Section divider
  doc.setDrawColor(...BRAND_LIGHT);
  doc.setLineWidth(0.4);
  doc.line(labelX, metaY - 4, pageW - 20, metaY - 4);

  const metaItems: Array<[string, string]> = [
    ['Date', formatDate(options.date, locale)],
    ['Sections', String(sectionCount)],
    ['Positions', String(itemCount)],
    ...(resourceCount > 0 ? [['Resources', String(resourceCount)] as [string, string]] : []),
    ['Direct Cost', formatCurrency(options.directCost, options.currency, locale)],
    ['Markups', options.markupTotals.map((m) => `${m.name} ${m.percentage}%`).join(', ') || 'None'],
    ['Net Total', formatCurrency(options.netTotal, options.currency, locale)],
    ['VAT', `${(options.vatRate * 100).toFixed(0)}% (${formatCurrency(options.vatAmount, options.currency, locale)})`],
  ];

  doc.setFontSize(9);
  for (let i = 0; i < metaItems.length; i++) {
    const item = metaItems[i]!;
    const y = metaY + i * 10;
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(...BRAND_MID);
    doc.text(item[0], labelX, y);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(...BRAND_DARK);
    doc.text(item[1], valueX, y);
  }

  // Gross total — highlighted
  const grossY = metaY + metaItems.length * 10 + 4;
  doc.setDrawColor(...BRAND_LIGHT);
  doc.line(labelX, grossY - 4, pageW - 20, grossY - 4);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.setTextColor(...BRAND_ACCENT);
  doc.text('Gross Total', labelX, grossY + 2);
  doc.text(formatCurrency(options.grossTotal, options.currency, locale), valueX, grossY + 2);

  // ── Signature block ─────────────────────────────────────────────────
  const sigY = pageH - 55;
  doc.setDrawColor(...BRAND_LIGHT);
  doc.setLineWidth(0.3);
  doc.line(labelX, sigY, pageW - 20, sigY);

  doc.setFontSize(8);
  doc.setTextColor(...BRAND_MID);
  doc.setFont('helvetica', 'normal');
  doc.text('Prepared by:', labelX, sigY + 10);
  doc.text('Approved by:', pageW / 2, sigY + 10);
  doc.line(labelX, sigY + 28, labelX + 60, sigY + 28);
  doc.line(pageW / 2, sigY + 28, pageW / 2 + 60, sigY + 28);
  doc.text('Name / Signature / Date', labelX, sigY + 33);
  doc.text('Name / Signature / Date', pageW / 2, sigY + 33);

  // Footer attribution
  doc.setFontSize(7);
  doc.setTextColor(...BRAND_MID);
  doc.text('Generated by OpenConstructionERP  |  openconstructionerp.com', labelX, pageH - 10);
}

/* ── Table of Contents ──────────────────────────────────────────────────── */

function renderTableOfContents(
  doc: jsPDF,
  sections: SectionEntry[],
): void {
  const pageW = doc.internal.pageSize.getWidth();

  // Section heading
  doc.setFillColor(...BRAND_DARK);
  doc.rect(0, 0, pageW, 18, 'F');
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(13);
  doc.setTextColor(...WHITE);
  doc.text('Table of Contents', 20, 12);

  doc.setTextColor(...BRAND_DARK);

  let y = 32;
  doc.setFontSize(9);
  for (const sec of sections) {
    doc.setFont('helvetica', 'normal');
    const label = `${sec.ordinal}  ${sec.description}`.trim();
    const lines = doc.splitTextToSize(label, pageW - 80) as string[];
    doc.text(lines, 20, y);

    // Dot leaders
    const textW = doc.getTextWidth(lines[0] ?? '');
    const dotsStart = 20 + textW + 2;
    const dotsEnd = pageW - 35;
    doc.setTextColor(...BRAND_LIGHT);
    const dotStr = '.'.repeat(Math.max(0, Math.floor((dotsEnd - dotsStart) / 2)));
    doc.text(dotStr, dotsStart, y);
    doc.setTextColor(...BRAND_DARK);

    // Page reference (filled post-render; placeholder during TOC pass)
    doc.setFont('helvetica', 'bold');
    doc.text(String(sec.pageNumber || '—'), pageW - 30, y, { align: 'right' });
    doc.setFont('helvetica', 'normal');

    y += lines.length * 6 + 2;
    if (y > doc.internal.pageSize.getHeight() - 25) {
      doc.addPage();
      y = 20;
    }
  }
}

/* ── Page footer ────────────────────────────────────────────────────────── */

function addPageFooters(doc: jsPDF, options: PdfReportOptions): void {
  const totalPages = (doc.internal as unknown as { getNumberOfPages: () => number }).getNumberOfPages();
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();

  for (let i = 1; i <= totalPages; i++) {
    doc.setPage(i);
    doc.setDrawColor(...BRAND_LIGHT);
    doc.setLineWidth(0.3);
    doc.line(15, pageH - 12, pageW - 15, pageH - 12);
    doc.setFontSize(7.5);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(...BRAND_MID);
    doc.text(options.boqTitle, 15, pageH - 7);
    doc.text(`Page ${i} of ${totalPages}`, pageW - 15, pageH - 7, { align: 'right' });
  }
}

/* ── BOQ table per section ──────────────────────────────────────────────── */

function renderBOQTables(
  doc: jsPDF,
  options: PdfReportOptions,
  locale: string,
  sectionEntries: SectionEntry[],
): void {
  const { sections, ungrouped } = buildSectionGroups(options.positions);
  const pageW = doc.internal.pageSize.getWidth();

  // Section heading bar
  doc.setFillColor(...BRAND_DARK);
  doc.rect(0, 0, pageW, 18, 'F');
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(13);
  doc.setTextColor(...WHITE);
  doc.text('Bill of Quantities', 20, 12);
  doc.setTextColor(...BRAND_DARK);

  let currentY = 26;

  const headerStyles: Parameters<typeof autoTable>[1]['headStyles'] = {
    fillColor: BRAND_DARK,
    textColor: WHITE,
    fontStyle: 'bold',
    fontSize: 8,
  };

  const renderSection = (
    ordinal: string,
    description: string,
    children: Position[],
    subtotal: number,
  ) => {
    // Section title row
    const sectionLabel = `${ordinal}  ${description}`.trim();
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9);
    doc.setTextColor(...BRAND_ACCENT);

    const labelLines = doc.splitTextToSize(sectionLabel, pageW - 40) as string[];
    doc.text(labelLines, 15, currentY);
    currentY += labelLines.length * 5 + 2;

    const body: string[][] = [];
    for (const p of children) {
      body.push([
        p.ordinal,
        p.description,
        p.unit,
        formatNumber(p.quantity, locale),
        formatCurrency(p.unit_rate, options.currency, locale),
        formatCurrency(p.total, options.currency, locale),
      ]);
      // Add resource sub-rows
      const meta = p.metadata ?? (p as unknown as Record<string, unknown>).metadata_;
      const resources = (meta && Array.isArray((meta as Record<string, unknown>).resources))
        ? (meta as Record<string, unknown>).resources as Array<{ name: string; type: string; unit: string; quantity: number; unit_rate: number; total?: number }>
        : [];
      for (const r of resources) {
        const rTotal = r.total ?? r.quantity * r.unit_rate;
        body.push([
          '',
          `  \u2514 ${r.name}`,
          r.unit,
          formatNumber(r.quantity, locale),
          formatCurrency(r.unit_rate, options.currency, locale),
          formatCurrency(rTotal, options.currency, locale),
        ]);
      }
    }

    autoTable(doc, {
      startY: currentY,
      head: [['No.', 'Description', 'Unit', 'Qty', 'Unit Rate', 'Total']],
      body,
      headStyles: headerStyles,
      bodyStyles: { fontSize: 8, textColor: BRAND_DARK },
      alternateRowStyles: { fillColor: [248, 250, 252] as [number, number, number] },
      columnStyles: {
        0: { cellWidth: 18, fontStyle: 'bold' },
        1: { cellWidth: 'auto' },
        2: { cellWidth: 16, halign: 'center' },
        3: { cellWidth: 22, halign: 'right' },
        4: { cellWidth: 28, halign: 'right' },
        5: { cellWidth: 28, halign: 'right', fontStyle: 'bold' },
      },
      margin: { left: 15, right: 15 },
      theme: 'grid',
      tableLineColor: BRAND_LIGHT,
      tableLineWidth: 0.2,
      didDrawPage: () => {
        // Reset current Y after page break inside autoTable
      },
    });

    const tableEndY = (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable.finalY;

    // Subtotal row
    const subtotalY = tableEndY + 2;
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(8.5);
    doc.setTextColor(...BRAND_MID);
    const subtotalText = `Section Subtotal: ${formatCurrency(subtotal, options.currency, locale)}`;
    doc.text(subtotalText, pageW - 15, subtotalY, { align: 'right' });
    doc.setDrawColor(...BRAND_ACCENT);
    doc.setLineWidth(0.4);
    doc.line(pageW - 15 - doc.getTextWidth(subtotalText) - 2, subtotalY + 1, pageW - 15, subtotalY + 1);

    currentY = subtotalY + 10;
    if (currentY > doc.internal.pageSize.getHeight() - 35) {
      doc.addPage();
      currentY = 20;
    }
  };

  // Record page numbers for TOC
  for (let i = 0; i < sections.length; i++) {
    const sec = sections[i]!;
    const entry = sectionEntries[i];
    if (entry) {
      entry.pageNumber = (doc.internal as unknown as { getCurrentPageInfo: () => { pageNumber: number } }).getCurrentPageInfo().pageNumber;
    }
    renderSection(sec.ordinal, sec.description, sec.children, sec.subtotal);
  }

  // Ungrouped positions (if any)
  if (ungrouped.length > 0) {
    const ungroupedSubtotal = ungrouped.reduce((sum, p) => sum + p.total, 0);
    renderSection('', 'Ungrouped Items', ungrouped, ungroupedSubtotal);
  }
}

/* ── Summary page ───────────────────────────────────────────────────────── */

function renderSummary(
  doc: jsPDF,
  options: PdfReportOptions,
  locale: string,
): void {
  doc.addPage();
  const pageW = doc.internal.pageSize.getWidth();

  // Heading
  doc.setFillColor(...BRAND_DARK);
  doc.rect(0, 0, pageW, 18, 'F');
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(13);
  doc.setTextColor(...WHITE);
  doc.text('Cost Summary', 20, 12);

  // Section subtotals table
  const { sections, ungrouped } = buildSectionGroups(options.positions);
  const sectionRows = sections.map((s) => [
    `${s.ordinal}  ${s.description}`.trim(),
    formatCurrency(s.subtotal, options.currency, locale),
  ]);
  if (ungrouped.length > 0) {
    const ungroupedTotal = ungrouped.reduce((sum, p) => sum + p.total, 0);
    sectionRows.push(['Ungrouped Items', formatCurrency(ungroupedTotal, options.currency, locale)]);
  }

  if (sectionRows.length > 0) {
    autoTable(doc, {
      startY: 24,
      head: [['Section', 'Subtotal']],
      body: sectionRows,
      headStyles: { fillColor: BRAND_MID, textColor: WHITE, fontSize: 8.5 },
      bodyStyles: { fontSize: 8.5, textColor: BRAND_DARK },
      alternateRowStyles: { fillColor: [248, 250, 252] as [number, number, number] },
      columnStyles: {
        0: { cellWidth: 'auto' },
        1: { cellWidth: 40, halign: 'right' },
      },
      margin: { left: 15, right: 15 },
      theme: 'grid',
      tableLineColor: BRAND_LIGHT,
      tableLineWidth: 0.2,
    });
  }

  const afterSectionsY = (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable?.finalY ?? 24;

  // Financial summary table
  const summaryRows: [string, string][] = [
    ['Direct Cost', formatCurrency(options.directCost, options.currency, locale)],
  ];

  for (const m of options.markupTotals) {
    summaryRows.push([
      `${m.name} (${m.percentage}%)`,
      formatCurrency(m.amount, options.currency, locale),
    ]);
  }

  const vatLabel = `VAT (${(options.vatRate * 100).toFixed(0)}%)`;

  autoTable(doc, {
    startY: afterSectionsY + 10,
    head: [['Item', 'Amount']],
    body: [
      ...summaryRows,
      ['Net Total', formatCurrency(options.netTotal, options.currency, locale)],
      [vatLabel, formatCurrency(options.vatAmount, options.currency, locale)],
    ],
    headStyles: { fillColor: BRAND_MID, textColor: WHITE, fontSize: 8.5 },
    bodyStyles: { fontSize: 8.5, textColor: BRAND_DARK },
    alternateRowStyles: { fillColor: [248, 250, 252] as [number, number, number] },
    columnStyles: {
      0: { cellWidth: 'auto' },
      1: { cellWidth: 40, halign: 'right' },
    },
    margin: { left: 15, right: 15 },
    theme: 'grid',
    tableLineColor: BRAND_LIGHT,
    tableLineWidth: 0.2,
  });

  const afterSummaryY = (doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable?.finalY ?? afterSectionsY + 10;

  // Gross total highlight box
  const boxY = afterSummaryY + 8;
  doc.setFillColor(...BRAND_DARK);
  doc.roundedRect(15, boxY, pageW - 30, 16, 3, 3, 'F');

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(11);
  doc.setTextColor(...WHITE);
  doc.text('GROSS TOTAL', 22, boxY + 10);
  doc.text(formatCurrency(options.grossTotal, options.currency, locale), pageW - 22, boxY + 10, { align: 'right' });
}

/* ── Main export function ───────────────────────────────────────────────── */

/**
 * Generates a professional A4 PDF report for a BOQ and triggers a browser
 * download. The report includes:
 *  - Cover page with project name, BOQ title, date, and key metrics
 *  - Table of Contents (when there are multiple sections)
 *  - BOQ tables grouped by section with subtotals
 *  - Cost summary: Direct Cost, Markups (itemised), Net Total, VAT, Gross Total
 *  - Page footers with "Page X of Y"
 */
export function generateBOQPdf(options: PdfReportOptions): void {
  const locale = options.locale ?? 'en-US';

  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'mm',
    format: 'a4',
  });

  // PDF metadata — embedded identity markers
  doc.setProperties({
    title: options.projectName || 'BOQ Report',
    subject: 'Bill of Quantities',
    author: 'OpenConstructionERP — DataDrivenConstruction',
    creator: 'DDC-CWICR-OE/1.5',
    keywords: 'BOQ, OpenConstructionERP, DDC, CWICR',
  });

  // ── 1. Cover page ──────────────────────────────────────────────────────
  renderCoverPage(doc, options, locale);

  // ── 2. Prepare section entries for TOC ────────────────────────────────
  const { sections } = buildSectionGroups(options.positions);
  const sectionEntries: SectionEntry[] = sections.map((s) => ({
    ordinal: s.ordinal,
    description: s.description,
    subtotal: s.subtotal,
    pageNumber: 0,
  }));

  // ── 3. Table of Contents (only if there are multiple sections) ─────────
  const hasTOC = sections.length > 1;
  if (hasTOC) {
    doc.addPage();
    // TOC is rendered with placeholder page numbers first; we re-render
    // it after the BOQ tables to fill in correct page references.
    renderTableOfContents(doc, sectionEntries);
  }

  // ── 4. BOQ tables ──────────────────────────────────────────────────────
  doc.addPage();
  renderBOQTables(doc, options, locale, sectionEntries);

  // ── 5. Re-render TOC with actual page numbers ─────────────────────────
  if (hasTOC) {
    // TOC is on page 2 (cover is page 1)
    doc.setPage(2);
    // Clear the page by drawing white rectangle
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    doc.setFillColor(...WHITE);
    doc.rect(0, 0, pageW, pageH, 'F');
    renderTableOfContents(doc, sectionEntries);
  }

  // ── 6. Summary page ────────────────────────────────────────────────────
  renderSummary(doc, options, locale);

  // ── 7. Page footers ────────────────────────────────────────────────────
  addPageFooters(doc, options);

  // ── 8. Download ───────────────────────────────────────────────────────
  const safeName = options.boqTitle.replace(/[^a-zA-Z0-9_\- ]/g, '').trim() || 'BOQ';
  doc.save(`${safeName}.pdf`);
}
