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
 * Recursively extract text from DetailTxt > Text or CompleteText nodes,
 * collapsing whitespace into a single line.
 */
function extractDescription(itemEl: Element): string {
  // Prefer CompleteText > DetailTxt > Text chain (X83 / X81 standard path)
  const detailText = itemEl.querySelector('CompleteText > DetailTxt > Text');
  if (detailText?.textContent) {
    return detailText.textContent.replace(/\s+/g, ' ').trim();
  }

  // Fall back to any nested <Text> element inside Description
  const descEl = itemEl.querySelector('Description');
  if (descEl) {
    const textEl = descEl.querySelector('Text');
    if (textEl?.textContent) {
      return textEl.textContent.replace(/\s+/g, ' ').trim();
    }
    return descEl.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  }

  // Last resort: ShortText
  const shortText = itemEl.querySelector('ShortText');
  return shortText?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
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
  const xmlString = await file.text();
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
