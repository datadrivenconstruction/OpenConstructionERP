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
// Unit code mapping — internal canonical units → GAEB-DA short codes
// ---------------------------------------------------------------------------

/**
 * Map our internal canonical units (lowercase ASCII) to the short codes
 * that GAEB-compliant readers expect in the <QU> element.
 *
 * GAEB DA XML doesn't enforce a closed list, but DACH AVA software (RIB iTWO,
 * California, Sirados, ORCA) consistently uses these symbolic forms with
 * superscript digits and German abbreviations.
 *
 * Anything not in this map is forwarded verbatim — units.py:APPROVED_UNITS
 * already keeps the safe shape, so locale-specific spellings round-trip.
 */
const GAEB_UNIT_CODES: Record<string, string> = {
  // length
  m: 'm',
  mm: 'mm',
  cm: 'cm',
  km: 'km',
  lm: 'm', // linear meter — same code as m in GAEB
  ll: 'm',
  ft: 'ft',
  in: 'in',
  // area
  m2: 'm²',
  cm2: 'cm²',
  ft2: 'ft²',
  // volume
  m3: 'm³',
  cm3: 'cm³',
  l: 'l',
  ft3: 'ft³',
  // mass
  kg: 'kg',
  g: 'g',
  t: 't',
  // counts / lump
  pcs: 'Stk',
  ea: 'Stk',
  no: 'Stk',
  set: 'Stk',
  lsum: 'psch',
  ls: 'psch',
  // time / labour
  hr: 'Std',
  h: 'Std',
  hrs: 'Std',
  hour: 'Std',
  hours: 'Std',
  day: 'Tag',
  days: 'Tag',
  wk: 'Wo',
  month: 'Mon',
};

/**
 * Map a canonical internal unit to its GAEB-DA short code.
 * Falls back to a sanitised version of the input if no mapping exists.
 */
export function toGaebUnitCode(unit: string | undefined | null): string {
  if (!unit) return 'Stk';
  const trimmed = unit.trim();
  if (!trimmed) return 'Stk';
  const lower = trimmed.toLowerCase();
  return GAEB_UNIT_CODES[lower] ?? trimmed;
}

/**
 * Reverse mapping for round-trip imports — turn a GAEB-DA short code back
 * into our canonical lowercase ASCII unit. Exported so the importer can
 * call it; not used inside this file.
 */
export function fromGaebUnitCode(code: string | undefined | null): string {
  if (!code) return '';
  const trimmed = code.trim();
  if (!trimmed) return '';
  // Accept common GAEB short codes and normalise back to canonical units.
  const map: Record<string, string> = {
    'm²': 'm2',
    m2: 'm2',
    'm³': 'm3',
    m3: 'm3',
    'cm²': 'cm2',
    'cm³': 'cm3',
    'ft²': 'ft2',
    'ft³': 'ft3',
    Stk: 'pcs',
    stk: 'pcs',
    St: 'pcs',
    psch: 'lsum',
    Psch: 'lsum',
    Std: 'hr',
    std: 'hr',
    Tag: 'day',
    tag: 'day',
    Wo: 'wk',
    wo: 'wk',
    Mon: 'month',
    mon: 'month',
  };
  return map[trimmed] ?? trimmed;
}

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
// Section grouping (multi-level)
// ---------------------------------------------------------------------------

/**
 * One node of the BoQ tree. A node is either a category (Los / Titel) holding
 * children, or a leaf containing one or more positions.
 *
 * GAEB DA XML 3.3 supports arbitrarily-deep BoQCtgy nesting (e.g. Los → Titel
 * → Untertitel → Position). The previous implementation flattened everything
 * to one level, losing structure on round-trip.
 */
interface SectionNode {
  ordinal: string;
  /** Last component of the ordinal (RNoPart for this category). */
  rnoPart: string;
  label: string;
  /** Direct child positions of this category (excluding sub-categories). */
  positions: ExportPosition[];
  /** Nested sub-categories. */
  children: SectionNode[];
}

/**
 * Build a multi-level section tree from a flat list of positions.
 *
 * The tree shape is inferred from the dotted ordinal — each prefix of an
 * ordinal becomes a category. Example: ordinals
 *
 *   01           (section)        → Los 1
 *   01.01        (section)        → Titel 1.1
 *   01.01.001    (position)       → goes into Titel 1.1
 *   01.02.003    (position)       → goes into Titel 1.2 (auto-created)
 *
 * Section header rows (isSection=true) provide the human-readable label;
 * if no section row exists at a given ordinal, the label falls back to
 * the position.section text or the ordinal itself.
 */
function buildSectionTree(positions: ExportPosition[]): SectionNode[] {
  // Index section rows by ordinal so we can attach labels later.
  const sectionRowByOrdinal = new Map<string, ExportPosition>();
  for (const p of positions) {
    if (p.isSection && p.ordinal) {
      sectionRowByOrdinal.set(p.ordinal, p);
    }
  }

  const root: SectionNode = {
    ordinal: '',
    rnoPart: '',
    label: '',
    positions: [],
    children: [],
  };

  /** Locate-or-create a SectionNode for the given ordinal path. */
  function ensureNode(parts: string[]): SectionNode {
    let node: SectionNode = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i] ?? '';
      const ordinal = parts.slice(0, i + 1).join('.');
      let child: SectionNode | undefined = node.children.find((c) => c.rnoPart === part);
      if (!child) {
        const sectionRow = sectionRowByOrdinal.get(ordinal);
        child = {
          ordinal,
          rnoPart: part,
          label: sectionRow?.description ?? '',
          positions: [],
          children: [],
        };
        node.children.push(child);
      }
      node = child;
    }
    return node;
  }

  // First pass: ensure every section row creates its node so empty
  // sections (no positions) survive into the export.
  for (const p of positions) {
    if (p.isSection && p.ordinal) {
      ensureNode(p.ordinal.split('.'));
    }
  }

  // Second pass: place each position under its parent category.
  for (const p of positions) {
    if (p.isSection) continue;

    const ordParts = p.ordinal.split('.').filter(Boolean);
    if (ordParts.length <= 1) {
      // Top-level position with no category prefix — bucket under "default".
      const def = ensureNode(['default']);
      if (!def.label) def.label = 'General';
      def.positions.push(p);
      continue;
    }

    // Parent ordinal = everything except the last segment
    const parentParts = ordParts.slice(0, -1);
    const node = ensureNode(parentParts);
    if (!node.label) {
      node.label = p.section ?? parentParts.join('.');
    }
    node.positions.push(p);
  }

  return root.children;
}

// ---------------------------------------------------------------------------
// GAEB XML 3.3 Generator
// ---------------------------------------------------------------------------

/**
 * Render one position as <Item> XML lines, including the multi-line
 * description if the source contains newlines.
 */
function renderItem(
  pos: ExportPosition,
  isX83: boolean,
  baseIndent: number,
  lines: string[],
): void {
  const itemOrdParts = pos.ordinal.split('.');
  const itemNo = itemOrdParts[itemOrdParts.length - 1] || pos.ordinal;

  lines.push(`${indent(baseIndent)}<Item RNoPart="${escapeXml(itemNo)}">`);

  // Quantity
  lines.push(`${indent(baseIndent + 1)}<Qty>${formatDecimal(pos.quantity)}</Qty>`);

  // Unit (mapped to GAEB-DA short code)
  const gaebUnit = toGaebUnitCode(pos.unit);
  lines.push(`${indent(baseIndent + 1)}<QU>${escapeXml(gaebUnit)}</QU>`);

  // Description — if source contains newlines, emit one <Text> per paragraph
  // so the structure round-trips. Single-line descriptions still produce one
  // <Text> element for readers that expect it.
  lines.push(`${indent(baseIndent + 1)}<Description>`);
  lines.push(`${indent(baseIndent + 2)}<CompleteText>`);
  lines.push(`${indent(baseIndent + 3)}<DetailTxt>`);
  const paragraphs = (pos.description ?? '')
    .split(/\n+/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  if (paragraphs.length === 0) {
    lines.push(`${indent(baseIndent + 4)}<Text></Text>`);
  } else {
    for (const para of paragraphs) {
      lines.push(`${indent(baseIndent + 4)}<Text>${escapeXml(para)}</Text>`);
    }
  }
  lines.push(`${indent(baseIndent + 3)}</DetailTxt>`);
  lines.push(`${indent(baseIndent + 2)}</CompleteText>`);

  // ShortText: first paragraph, truncated to 70 chars per GAEB convention.
  // No trailing ellipsis — many AVA readers display it verbatim.
  const firstPara = paragraphs[0] ?? pos.description ?? '';
  const shortText = firstPara.length > 70 ? firstPara.substring(0, 70) : firstPara;
  lines.push(`${indent(baseIndent + 2)}<ShortText>${escapeXml(shortText)}</ShortText>`);
  lines.push(`${indent(baseIndent + 1)}</Description>`);

  // Unit price (only in X83)
  if (isX83) {
    lines.push(`${indent(baseIndent + 1)}<UP>${formatDecimal(pos.unitRate, 2)}</UP>`);
    lines.push(`${indent(baseIndent + 1)}<IT>${formatDecimal(pos.total, 2)}</IT>`);
  }

  lines.push(`${indent(baseIndent)}</Item>`);
}

/** Recursively render a SectionNode and all its descendants. */
function renderSection(
  node: SectionNode,
  isX83: boolean,
  baseIndent: number,
  lines: string[],
): void {
  lines.push(`${indent(baseIndent)}<BoQCtgy RNoPart="${escapeXml(node.rnoPart)}">`);
  lines.push(`${indent(baseIndent + 1)}<LblTx>${escapeXml(node.label || node.rnoPart)}</LblTx>`);
  lines.push(`${indent(baseIndent + 1)}<BoQBody>`);

  // Render direct positions first (if any) inside an Itemlist
  if (node.positions.length > 0) {
    lines.push(`${indent(baseIndent + 2)}<Itemlist>`);
    for (const pos of node.positions) {
      renderItem(pos, isX83, baseIndent + 3, lines);
    }
    lines.push(`${indent(baseIndent + 2)}</Itemlist>`);
  }

  // Then render any nested sub-categories
  for (const child of node.children) {
    renderSection(child, isX83, baseIndent + 2, lines);
  }

  lines.push(`${indent(baseIndent + 1)}</BoQBody>`);
  lines.push(`${indent(baseIndent)}</BoQCtgy>`);
}

/** Count all positions in a section subtree (recursive). */
function countSections(nodes: SectionNode[]): number {
  let n = nodes.length;
  for (const node of nodes) {
    n += countSections(node.children);
  }
  return n;
}

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
  const sectionTree = buildSectionTree(positions);
  const sectionCount = countSections(sectionTree);
  const positionCount = nonSectionPositions.length;

  const lines: string[] = [];

  // XML header — UTF-8 (declared so importers honour it; we always emit UTF-8).
  lines.push('<?xml version="1.0" encoding="UTF-8"?>');
  // Namespace differs per format: DA83 (priced) vs DA81 (tender).
  const namespace = isX83
    ? 'http://www.gaeb.de/GAEB_DA_XML/DA83/3.3'
    : 'http://www.gaeb.de/GAEB_DA_XML/DA81/3.3';
  lines.push(`<GAEB xmlns="${namespace}">`);

  // GAEBInfo — spec-compliant VersMajor / VersMinor pair (Version is legacy
  // and not part of GAEB DA XML 3.3 schema).
  lines.push(`${indent(1)}<GAEBInfo>`);
  lines.push(`${indent(2)}<VersMajor>3</VersMajor>`);
  lines.push(`${indent(2)}<VersMinor>3</VersMinor>`);
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

  // BoQBody — render the full multi-level section tree
  lines.push(`${indent(3)}<BoQBody>`);
  for (const section of sectionTree) {
    renderSection(section, isX83, 4, lines);
  }
  lines.push(`${indent(3)}</BoQBody>`);
  lines.push(`${indent(2)}</BoQ>`);
  lines.push(`${indent(1)}</${mainTag}>`);
  lines.push('</GAEB>');

  const xml = lines.join('\n');
  const ext = isX83 ? 'x83' : 'x81';
  // Filename: <project>-<boq>.<ext> — keeps both project and BOQ context.
  // Falls back gracefully when project name is empty.
  const safeProject = (projectName || '').replace(/[^a-zA-Z0-9_-]/g, '_');
  const safeBoq = (boqName || 'export').replace(/[^a-zA-Z0-9_-]/g, '_');
  const filename = safeProject ? `${safeProject}-${safeBoq}.${ext}` : `${safeBoq}.${ext}`;

  return { xml, filename, positionCount, sectionCount };
}

/** Download the generated GAEB XML as a file. */
export function downloadGAEBXML(result: GAEBExportResult): void {
  const blob = new Blob([result.xml], { type: 'application/xml; charset=utf-8' });
  triggerDownload(blob, result.filename);
}
