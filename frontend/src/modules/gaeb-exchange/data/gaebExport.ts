/**
 * Client-side GAEB DA XML 3.3 export generator.
 *
 * Generates valid GAEB DA XML X83 (bid submission with prices)
 * and X81 (tender specification without prices) documents.
 *
 * Reference: GAEB DA XML 3.3 (Gemeinsamer Ausschuss Elektronik im Bauwesen)
 */

import { triggerDownload } from '@/shared/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type GAEBExportFormat = 'X81' | 'X83';

export interface ExportPosition {
  id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unitRate: number;
  total: number;
  section?: string;
  parentId?: string | null;
  isSection?: boolean;
}

export interface GAEBExportOptions {
  /** Document format: X81 (no prices) or X83 (with prices) */
  format: GAEBExportFormat;
  /** Project/BOQ name */
  projectName: string;
  /** BOQ name / Leistungsverzeichnis name */
  boqName: string;
  /** Currency code (default: EUR) */
  currency?: string;
  /** Positions to export */
  positions: ExportPosition[];
  /** Award info (for X83) */
  awardInfo?: {
    bidderName?: string;
    bidderCity?: string;
    bidDate?: string;
  };
}

export interface GAEBExportResult {
  /** Generated XML string */
  xml: string;
  /** Suggested filename */
  filename: string;
  /** Number of positions exported */
  positionCount: number;
  /** Number of sections exported */
  sectionCount: number;
}

// ---------------------------------------------------------------------------
// XML helpers
// ---------------------------------------------------------------------------

function escapeXml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function formatDecimal(value: number, decimals = 3): string {
  return value.toFixed(decimals);
}

function indent(level: number): string {
  return '  '.repeat(level);
}

// ---------------------------------------------------------------------------
// Section grouping
// ---------------------------------------------------------------------------

interface SectionNode {
  ordinal: string;
  label: string;
  positions: ExportPosition[];
}

function groupIntoSections(positions: ExportPosition[]): SectionNode[] {
  const sections = new Map<string, SectionNode>();
  const ungrouped: ExportPosition[] = [];

  for (const pos of positions) {
    if (pos.isSection) continue; // Skip section header rows

    const sectionKey = pos.section || pos.ordinal.split('.').slice(0, -1).join('.') || 'default';
    if (!sections.has(sectionKey)) {
      // Find corresponding section row
      const sectionRow = positions.find(
        (p) => p.isSection && (p.ordinal === sectionKey || p.description === pos.section),
      );
      sections.set(sectionKey, {
        ordinal: sectionRow?.ordinal || sectionKey,
        label: sectionRow?.description || pos.section || sectionKey,
        positions: [],
      });
    }
    sections.get(sectionKey)!.positions.push(pos);
  }

  // If everything is ungrouped, create a single default section
  if (sections.size === 0 && ungrouped.length > 0) {
    sections.set('01', { ordinal: '01', label: 'General', positions: ungrouped });
  }

  return Array.from(sections.values());
}

// ---------------------------------------------------------------------------
// GAEB XML 3.3 Generator
// ---------------------------------------------------------------------------

export function generateGAEBXML(options: GAEBExportOptions): GAEBExportResult {
  const {
    format,
    projectName,
    boqName,
    currency = 'EUR',
    positions,
    awardInfo,
  } = options;

  const isX83 = format === 'X83';
  const nonSectionPositions = positions.filter((p) => !p.isSection);
  const sections = groupIntoSections(positions);
  const sectionCount = sections.length;
  const positionCount = nonSectionPositions.length;

  const lines: string[] = [];

  // XML header
  lines.push('<?xml version="1.0" encoding="UTF-8"?>');
  lines.push('<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">');

  // GAEBInfo
  lines.push(`${indent(1)}<GAEBInfo>`);
  lines.push(`${indent(2)}<Version>3.3</Version>`);
  lines.push(`${indent(2)}<VersDate>2013-02</VersDate>`);
  lines.push(`${indent(2)}<Date>${new Date().toISOString().split('T')[0]}</Date>`);
  lines.push(`${indent(2)}<ProgSystem>OpenEstimate</ProgSystem>`);
  lines.push(`${indent(2)}<ProgSystemVers>1.0</ProgSystemVers>`);
  lines.push(`${indent(1)}</GAEBInfo>`);

  // PrjInfo
  lines.push(`${indent(1)}<PrjInfo>`);
  lines.push(`${indent(2)}<NamePrj>${escapeXml(projectName)}</NamePrj>`);
  lines.push(`${indent(2)}<Cur>${currency}</Cur>`);
  lines.push(`${indent(2)}<CurLbl>${currency === 'EUR' ? '€' : currency}</CurLbl>`);
  lines.push(`${indent(1)}</PrjInfo>`);

  // Main section: Award (X83) or Tender (X81)
  const mainTag = isX83 ? 'Award' : 'Tender';
  lines.push(`${indent(1)}<${mainTag}>`);

  // Award/Tender info
  if (isX83) {
    lines.push(`${indent(2)}<AwardInfo>`);
    lines.push(`${indent(3)}<Dp>${new Date().toISOString().split('T')[0]}</Dp>`);
    if (awardInfo?.bidderName) {
      lines.push(`${indent(3)}<Bidder>`);
      lines.push(`${indent(4)}<Name1>${escapeXml(awardInfo.bidderName)}</Name1>`);
      if (awardInfo.bidderCity) {
        lines.push(`${indent(4)}<PCode>${escapeXml(awardInfo.bidderCity)}</PCode>`);
      }
      lines.push(`${indent(3)}</Bidder>`);
    }
    lines.push(`${indent(2)}</AwardInfo>`);
  }

  // BoQ
  lines.push(`${indent(2)}<BoQ>`);
  lines.push(`${indent(3)}<BoQInfo>`);
  lines.push(`${indent(4)}<Name>${escapeXml(boqName)}</Name>`);
  lines.push(`${indent(4)}<LblBoQ>${escapeXml(boqName)}</LblBoQ>`);
  lines.push(`${indent(3)}</BoQInfo>`);

  // BoQBody
  lines.push(`${indent(3)}<BoQBody>`);

  // Write each section as BoQCtgy
  for (const section of sections) {
    const sectionOrdParts = section.ordinal.split('.');
    const sectionNo = sectionOrdParts[sectionOrdParts.length - 1] || section.ordinal;

    lines.push(`${indent(4)}<BoQCtgy RNoPart="${escapeXml(sectionNo)}">`);
    lines.push(`${indent(5)}<LblTx>${escapeXml(section.label)}</LblTx>`);

    // BoQBody inside category
    lines.push(`${indent(5)}<BoQBody>`);
    lines.push(`${indent(6)}<Itemlist>`);

    for (const pos of section.positions) {
      const itemOrdParts = pos.ordinal.split('.');
      const itemNo = itemOrdParts[itemOrdParts.length - 1] || pos.ordinal;

      lines.push(`${indent(7)}<Item RNoPart="${escapeXml(itemNo)}">`);

      // Quantity
      lines.push(`${indent(8)}<Qty>${formatDecimal(pos.quantity)}</Qty>`);

      // Unit
      lines.push(`${indent(8)}<QU>${escapeXml(pos.unit || 'pcs')}</QU>`);

      // Description
      lines.push(`${indent(8)}<Description>`);
      lines.push(`${indent(9)}<CompleteText>`);
      lines.push(`${indent(10)}<DetailTxt>`);
      lines.push(`${indent(11)}<Text>${escapeXml(pos.description)}</Text>`);
      lines.push(`${indent(10)}</DetailTxt>`);
      lines.push(`${indent(9)}</CompleteText>`);

      // ShortText (first 70 chars)
      const shortText = pos.description.length > 70 ? pos.description.substring(0, 67) + '...' : pos.description;
      lines.push(`${indent(9)}<ShortText>${escapeXml(shortText)}</ShortText>`);
      lines.push(`${indent(8)}</Description>`);

      // Unit price (only in X83)
      if (isX83) {
        lines.push(`${indent(8)}<UP>${formatDecimal(pos.unitRate, 2)}</UP>`);
        lines.push(`${indent(8)}<IT>${formatDecimal(pos.total, 2)}</IT>`);
      }

      lines.push(`${indent(7)}</Item>`);
    }

    lines.push(`${indent(6)}</Itemlist>`);
    lines.push(`${indent(5)}</BoQBody>`);
    lines.push(`${indent(4)}</BoQCtgy>`);
  }

  lines.push(`${indent(3)}</BoQBody>`);
  lines.push(`${indent(2)}</BoQ>`);
  lines.push(`${indent(1)}</${mainTag}>`);
  lines.push('</GAEB>');

  const xml = lines.join('\n');
  const ext = isX83 ? 'x83' : 'x81';
  const safeName = boqName.replace(/[^a-zA-Z0-9_-]/g, '_');
  const filename = `${safeName}.${ext}`;

  return { xml, filename, positionCount, sectionCount };
}

/** Download the generated GAEB XML as a file. */
export function downloadGAEBXML(result: GAEBExportResult): void {
  const blob = new Blob([result.xml], { type: 'application/xml; charset=utf-8' });
  triggerDownload(blob, result.filename);
}
