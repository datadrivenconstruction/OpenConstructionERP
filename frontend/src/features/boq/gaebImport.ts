/**
 * GAEB XML Import Parser for OpenEstimate.
 *
 * Supports GAEB DA XML formats:
 *   - X81 (Leistungsverzeichnis / tender specification, no prices)
 *   - X83 (Angebotsabgabe / bid submission, includes unit prices)
 *
 * Reference: GAEB DA XML 3.3 schema (Gemeinsamer Ausschuss Elektronik im Bauwesen)
 * DOMParser is browser-native — zero extra dependencies.
 */

import { boqApi, type CreatePositionData } from './api';

// ---------------------------------------------------------------------------
// Encoding sniffing
// ---------------------------------------------------------------------------

/**
 * Decode a raw byte buffer using the encoding declared in the XML prolog
 * (`<?xml ... encoding="..."?>`). Falls back to UTF-8.
 *
 * Many DACH-region GAEB exports are still produced in ISO-8859-1 / Windows-1252
 * because legacy AVA software defaults to those code pages. Reading them as
 * UTF-8 corrupts every umlaut (ä/ö/ü/ß) into U+FFFD.
 *
 * Strategy: read the first ~1024 bytes as ASCII (which works for any
 * single-byte legacy encoding too, since the XML prolog is pure ASCII),
 * extract the declared encoding, then decode the full buffer with the
 * matching TextDecoder.
 */
export function decodeXmlBuffer(buffer: ArrayBuffer): string {
  const head = new Uint8Array(buffer, 0, Math.min(1024, buffer.byteLength));
  const ascii = new TextDecoder('ascii').decode(head);
  const match = ascii.match(/<\?xml[^?]*encoding=["']([^"']+)["']/i);
  const declared = match?.[1]?.toLowerCase().trim();

  // Map common legacy aliases to canonical TextDecoder labels.
  const aliasMap: Record<string, string> = {
    'iso-8859-1': 'iso-8859-1',
    'iso8859-1': 'iso-8859-1',
    latin1: 'iso-8859-1',
    'iso-8859-15': 'iso-8859-15',
    'windows-1252': 'windows-1252',
    'cp1252': 'windows-1252',
    'utf-8': 'utf-8',
    utf8: 'utf-8',
    'utf-16': 'utf-16',
  };

  const encoding = (declared && aliasMap[declared]) ?? declared ?? 'utf-8';
  try {
    return new TextDecoder(encoding, { fatal: false }).decode(buffer);
  } catch {
    // Unsupported encoding — fall back to UTF-8 rather than crash.
    return new TextDecoder('utf-8', { fatal: false }).decode(buffer);
  }
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** A single parsed BOQ position extracted from a GAEB XML document. */
export interface GAEBPosition {
  /** Hierarchical ordinal, e.g. "01.02.003" (built from OrdinalNo chain). */
  ordinal: string;
  /** Full item description stripped of XML tags. */
  description: string;
  /** Unit of measure from QU element, e.g. "m2", "m3", "Stk". */
  unit: string;
  /** Item quantity from Qty element; defaults to 0 if missing or unparseable. */
  quantity: number;
  /** Unit rate (Einheitspreis) from UP element; defaults to 0 (absent in X81). */
  unitRate: number;
  /** Section / category label from the nearest ancestor LblTx, if any. */
  section?: string;
}

/** Result returned by importGAEBToBOQ. */
export interface GAEBImportResult {
  /** Number of positions successfully created via the API. */
  imported: number;
  /** Human-readable error messages for positions that failed. */
  errors: string[];
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Safely extract trimmed text content from the first matching descendant. */
function getText(parent: Element, tagName: string): string {
  const el = parent.querySelector(tagName);
  return el?.textContent?.trim() ?? '';
}

/**
 * Normalise whitespace inside a single GAEB text run while preserving the
 * paragraph structure of multi-line descriptions.
 *
 * Per GAEB DA XML 3.3, long-text positions ship as a sequence of <p> blocks
 * inside <DetailTxt> (or as text nodes separated by <br/>). Collapsing every
 * whitespace run to a single space — as the previous implementation did —
 * destroys that structure and turns multi-paragraph descriptions into one
 * unreadable line. We only collapse runs of spaces/tabs, leaving newlines.
 */
function normaliseRunWhitespace(text: string): string {
  // Collapse runs of horizontal whitespace (spaces, tabs) but keep newlines.
  return text
    .replace(/\r\n?/g, '\n') // CRLF / CR -> LF
    .replace(/[ \t]+/g, ' ')
    .replace(/[ \t]*\n[ \t]*/g, '\n')
    .replace(/\n{3,}/g, '\n\n') // collapse 3+ blank lines to one
    .trim();
}

/**
 * Recursively extract text from DetailTxt > Text / <p> nodes, preserving
 * paragraph breaks as `\n` so multi-paragraph descriptions round-trip.
 */
function extractDescription(itemEl: Element): string {
  // Prefer CompleteText > DetailTxt — may contain multiple <p> or <Text> nodes
  const detailTxt = itemEl.querySelector('CompleteText > DetailTxt');
  if (detailTxt) {
    const blocks: string[] = [];
    for (const child of Array.from(detailTxt.children)) {
      const tag = child.tagName;
      if (tag === 'Text' || tag === 'p' || tag === 'P') {
        const t = child.textContent ?? '';
        if (t.trim()) blocks.push(t);
      } else if (tag === 'br' || tag === 'BR') {
        blocks.push('');
      }
    }
    if (blocks.length > 0) {
      return normaliseRunWhitespace(blocks.join('\n'));
    }
    // No structured children — flatten the DetailTxt textContent
    if (detailTxt.textContent) {
      return normaliseRunWhitespace(detailTxt.textContent);
    }
  }

  // Fall back to any nested <Text> element inside Description
  const descEl = itemEl.querySelector('Description');
  if (descEl) {
    const textEl = descEl.querySelector('Text');
    if (textEl?.textContent) {
      return normaliseRunWhitespace(textEl.textContent);
    }
    return normaliseRunWhitespace(descEl.textContent ?? '');
  }

  // Last resort: ShortText
  const shortText = itemEl.querySelector('ShortText');
  return normaliseRunWhitespace(shortText?.textContent ?? '');
}

/** Parse a decimal number from a string, returning the fallback on failure. */
function parseDecimal(value: string, fallback = 0): number {
  if (!value) return fallback;
  // GAEB uses period or comma as decimal separator depending on locale
  const normalised = value.trim().replace(',', '.');
  const parsed = parseFloat(normalised);
  return isNaN(parsed) ? fallback : parsed;
}

/**
 * Build a dot-separated ordinal string from an array of ordinal number parts.
 * Leading zeros are preserved as they appear in the GAEB document.
 *
 * @example buildOrdinal(['01', '02', '003']) → '01.02.003'
 */
function buildOrdinal(parts: string[]): string {
  return parts.filter(Boolean).join('.');
}

/**
 * Recursively walk BoQCtgy (category / section) and Itemlist > Item nodes.
 *
 * @param el          Current element to process.
 * @param ordinalParts Accumulated ordinal parts from ancestor categories.
 * @param sectionLabel Label of the nearest ancestor BoQCtgy (LblTx text).
 * @param results      Accumulator array — items are pushed here.
 */
function walkBoQBody(
  el: Element,
  ordinalParts: string[],
  sectionLabel: string | undefined,
  results: GAEBPosition[],
): void {
  // Iterate direct children only — avoids double-processing nested nodes
  for (const child of Array.from(el.children)) {
    const tag = child.tagName;

    if (tag === 'BoQCtgy') {
      // Determine category ordinal number
      const ctgyNo = child.getAttribute('RNoPart') ?? child.getAttribute('OrdinalNo') ?? '';
      const newOrdinalParts = ctgyNo ? [...ordinalParts, ctgyNo] : ordinalParts;

      // Determine section label for items that fall under this category
      const lblTxEl = child.querySelector(':scope > LblTx, :scope > Description > LblTx');
      const label = lblTxEl?.textContent?.replace(/\s+/g, ' ').trim() || sectionLabel;
      // Track parent ordinals so nested categories preserve hierarchy in the
      // emitted GAEBPosition.section path. (Used by exporter round-trip.)

      // Recurse into nested BoQBody inside this category
      for (const nestedBody of Array.from(child.children)) {
        if (nestedBody.tagName === 'BoQBody') {
          walkBoQBody(nestedBody, newOrdinalParts, label, results);
        }
      }
    } else if (tag === 'Itemlist') {
      // Walk all Item elements inside the Itemlist
      for (const item of Array.from(child.children)) {
        if (item.tagName !== 'Item') continue;
        parseItem(item, ordinalParts, sectionLabel, results);
      }
    } else if (tag === 'Item') {
      // Some documents place Item directly in BoQBody (non-standard but seen)
      parseItem(child, ordinalParts, sectionLabel, results);
    }
  }
}

/** Extract a single Item element into a GAEBPosition and push to results. */
function parseItem(
  itemEl: Element,
  ordinalParts: string[],
  sectionLabel: string | undefined,
  results: GAEBPosition[],
): void {
  // Item ordinal number (RNoPart or OrdinalNo attribute, or child element)
  const itemNo =
    itemEl.getAttribute('RNoPart') ??
    itemEl.getAttribute('OrdinalNo') ??
    getText(itemEl, 'OrdinalNo') ??
    '';

  const ordinal = buildOrdinal([...ordinalParts, itemNo]);

  // Quantity: Qty attribute or child element
  const qtyAttr = itemEl.getAttribute('Qty') ?? '';
  const qtyText = getText(itemEl, 'Qty');
  const quantity = parseDecimal(qtyAttr || qtyText);

  // Unit of measure: QU element
  const unit = getText(itemEl, 'QU');

  // Description
  const description = extractDescription(itemEl);

  // Unit rate (Einheitspreis): UP element — absent in X81
  const upText = getText(itemEl, 'UP');
  const unitRate = parseDecimal(upText);

  results.push({
    ordinal,
    description,
    unit,
    quantity,
    unitRate,
    ...(sectionLabel !== undefined ? { section: sectionLabel } : {}),
  });
}

// ---------------------------------------------------------------------------
// Public functions
// ---------------------------------------------------------------------------

/**
 * Parse a GAEB DA XML string (X81 or X83) and return a flat list of positions.
 *
 * Uses the browser-native DOMParser — no external dependencies.
 *
 * @param xmlString Raw XML content of the GAEB file.
 * @returns         Array of GAEBPosition objects; empty array on parse error.
 */
export function parseGAEBXML(xmlString: string): GAEBPosition[] {
  if (!xmlString || !xmlString.trim()) {
    return [];
  }

  let doc: Document;
  try {
    const parser = new DOMParser();
    doc = parser.parseFromString(xmlString, 'application/xml');
  } catch {
    return [];
  }

  // Check for XML parse errors (DOMParser returns a parsererror document)
  const parseError = doc.querySelector('parsererror');
  if (parseError) {
    return [];
  }

  // Accept both <GAEB> root element (standard) and any root wrapping a BoQ
  const results: GAEBPosition[] = [];

  // Find all top-level BoQBody elements — works for X81 and X83
  // Typical path: GAEB > Award (X83) / Tender (X81) > BoQ > BoQBody
  const boqBodies = doc.querySelectorAll('BoQ > BoQBody');

  if (boqBodies.length === 0) {
    // Non-standard: try any BoQBody in the document
    const anyBody = doc.querySelectorAll('BoQBody');
    for (const body of Array.from(anyBody)) {
      walkBoQBody(body, [], undefined, results);
    }
  } else {
    for (const body of Array.from(boqBodies)) {
      walkBoQBody(body, [], undefined, results);
    }
  }

  return results;
}

/**
 * Read a GAEB XML File, parse it, and POST all positions to the BOQ API.
 *
 * Positions are created sequentially to preserve ordinal ordering.
 * Individual failures are collected in `errors` without aborting the import.
 *
 * @param file  Browser File object (GAEB XML, typically .x83 / .x81 / .xml)
 * @param boqId Target BOQ identifier in OpenEstimate
 */
export async function importGAEBToBOQ(file: File, boqId: string): Promise<GAEBImportResult> {
  // Read raw bytes and decode using the encoding declared in the XML prolog.
  // file.text() always assumes UTF-8 and corrupts ä/ö/ü/ß in legacy
  // ISO-8859-1 / Windows-1252 GAEB exports — common in DACH AVA software.
  const buffer = await file.arrayBuffer();
  const xmlString = decodeXmlBuffer(buffer);
  const positions = parseGAEBXML(xmlString);

  let imported = 0;
  const errors: string[] = [];

  for (const pos of positions) {
    // Skip positions that have no description and no unit (likely header artifacts)
    if (!pos.description && !pos.unit) {
      continue;
    }

    const payload: CreatePositionData = {
      boq_id: boqId,
      ordinal: pos.ordinal || '000',
      description: pos.description || '(no description)',
      unit: pos.unit || 'pcs',
      quantity: pos.quantity,
      unit_rate: pos.unitRate,
      classification: {},
    };

    try {
      await boqApi.addPosition(payload);
      imported++;
    } catch (err) {
      const label = pos.ordinal ? `${pos.ordinal} — ${pos.description}` : pos.description;
      const message = err instanceof Error ? err.message : String(err);
      errors.push(`Failed to import position "${label}": ${message}`);
    }
  }

  return { imported, errors };
}
