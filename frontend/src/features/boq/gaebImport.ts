// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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

import i18n from '@/app/i18n';
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

/** One BoQCtgy level of a position's enclosing hierarchy (outermost first). */
export interface GAEBSectionRef {
  /** Full dotted ordinal of this category level, e.g. "01" or "01.02". */
  ordinal: string;
  /** Label from the category's own LblTx; empty when it has none. */
  label: string;
}

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
  /**
   * Full chain of enclosing BoQCtgy categories, outermost first. The importer
   * recreates these as section header rows so the LV hierarchy survives the
   * import (it used to be dropped: the preview showed an "Abschnitt" per row
   * while the imported BOQ ended up with zero sections).
   */
  sectionPath?: GAEBSectionRef[];
}

/** Result returned by importGAEBToBOQ. */
export interface GAEBImportResult {
  /** Number of positions successfully created via the API. */
  imported: number;
  /** Number of section header rows created from the BoQCtgy hierarchy. */
  sectionsCreated: number;
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

/** Parse a decimal number from a string, returning the fallback on failure.
 *
 * GAEB files in the wild (the format is DACH-centric) routinely carry German
 * number formatting with a dot thousands separator and a comma decimal
 * separator, e.g. ``"1.234,56"``. The previous implementation did a single
 * ``replace(',', '.')`` which turned ``"1.234,56"`` into ``"1.234.56"`` and
 * ``parseFloat`` then truncated it to ``1.234`` - silently losing three
 * orders of magnitude on a unit rate. This mirrors the backend importer's
 * proven ``safe_float`` separator logic: when both separators are present the
 * last-occurring one is the decimal point; a lone comma is the decimal
 * separator; multiple dots are thousands separators.
 */
function parseDecimal(value: string, fallback = 0): number {
  if (!value) return fallback;
  let numeric = value.trim();
  if (!numeric) return fallback;

  // Preserve a leading sign, then strip whitespace thousands separators.
  let sign = '';
  if (numeric[0] === '+' || numeric[0] === '-') {
    sign = numeric[0] === '-' ? '-' : '';
    numeric = numeric.slice(1).trim();
  }
  // Strip whitespace group separators, incl. non-breaking (U+00A0)
  // and narrow no-break (U+202F) spaces used to group thousands.
  numeric = numeric.replace(/\s/g, '');

  const hasDot = numeric.includes('.');
  const hasComma = numeric.includes(',');

  if (hasDot && hasComma) {
    // Both present -> the last-occurring separator is the decimal point.
    if (numeric.lastIndexOf(',') > numeric.lastIndexOf('.')) {
      numeric = numeric.replace(/\./g, '').replace(',', '.');
    } else {
      numeric = numeric.replace(/,/g, '');
    }
  } else if (hasComma) {
    // Single comma -> decimal (EU). Multiple commas -> US thousands.
    if ((numeric.match(/,/g) ?? []).length > 1) {
      numeric = numeric.replace(/,/g, '');
    } else {
      numeric = numeric.replace(',', '.');
    }
  } else if (hasDot && (numeric.match(/\./g) ?? []).length > 1) {
    // Multiple dots with no comma -> dots are thousands separators.
    numeric = numeric.replace(/\./g, '');
  }

  const parsed = parseFloat(`${sign}${numeric}`);
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
 * @param sectionPath  Chain of enclosing categories, outermost first.
 * @param results      Accumulator array — items are pushed here.
 */
function walkBoQBody(
  el: Element,
  ordinalParts: string[],
  sectionLabel: string | undefined,
  sectionPath: GAEBSectionRef[],
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
      const ownLabel = lblTxEl?.textContent?.replace(/\s+/g, ' ').trim() || '';
      const label = ownLabel || sectionLabel;
      // Extend the category chain: the level's ordinal is the FULL dotted
      // path ("01", "01.02", …) so the importer can key and recreate the
      // section rows exactly as the BOQ editor numbers them. A category
      // without any ordinal part cannot be keyed and keeps the parent path.
      const newSectionPath: GAEBSectionRef[] = ctgyNo
        ? [...sectionPath, { ordinal: buildOrdinal(newOrdinalParts), label: ownLabel }]
        : sectionPath;

      // Recurse into nested BoQBody inside this category
      for (const nestedBody of Array.from(child.children)) {
        if (nestedBody.tagName === 'BoQBody') {
          walkBoQBody(nestedBody, newOrdinalParts, label, newSectionPath, results);
        }
      }
    } else if (tag === 'Itemlist') {
      // Walk all Item elements inside the Itemlist
      for (const item of Array.from(child.children)) {
        if (item.tagName !== 'Item') continue;
        parseItem(item, ordinalParts, sectionLabel, sectionPath, results);
      }
    } else if (tag === 'Item') {
      // Some documents place Item directly in BoQBody (non-standard but seen)
      parseItem(child, ordinalParts, sectionLabel, sectionPath, results);
    }
  }
}

/** Extract a single Item element into a GAEBPosition and push to results. */
function parseItem(
  itemEl: Element,
  ordinalParts: string[],
  sectionLabel: string | undefined,
  sectionPath: GAEBSectionRef[],
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
    ...(sectionPath.length > 0 ? { sectionPath } : {}),
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
      walkBoQBody(body, [], undefined, [], results);
    }
  } else {
    for (const body of Array.from(boqBodies)) {
      walkBoQBody(body, [], undefined, [], results);
    }
  }

  return results;
}

/**
 * Truncate a human-facing finding/error text to a screen-safe length.
 *
 * Import findings must never reprint raw payloads (Langtext bodies, base64
 * blobs); they identify a position and state what went wrong. Anything
 * longer than `max` characters is cut and terminated with an ellipsis.
 */
export function truncateFinding(text: string, max = 300): string {
  const t = text ?? '';
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

/** GAEB DP (Datenaustauschphase) number → the family's phase label. */
const DP_TO_PHASE: Record<string, string> = {
  '80': 'X80',
  '81': 'X81',
  '82': 'X82',
  '83': 'X83',
  '84': 'X84',
  '85': 'X85',
  '86': 'X86',
  // Site phases. They share the BoQ tree but are not bills: X31 carries
  // measured quantities for positions that already exist and X89 an invoice
  // against them. Named here so an import can refuse them by name.
  '31': 'X31',
  '89': 'X89',
};

/**
 * True for a GAEB phase that must not be imported as a bill (X31, X89).
 *
 * Read as a bill, an X31 yields empty sections and an X89 its invoiced lines
 * as new positions. Both belong in the bill's own GAEB X31 / X89 dialog.
 */
export function isGAEBSitePhase(phase: string): boolean {
  return phase === 'X31' || phase === 'X89';
}

/**
 * Detect the GAEB exchange phase (X80..X86) from the document itself.
 *
 * Reads the ``<DP>`` / ``<DPType>`` phase number first, then falls back to
 * the ``DAnn`` token embedded in the root namespace
 * (``…/GAEB_DA_XML/DA83/3.3``) - the same order the backend importer uses,
 * so both pipelines label a file identically. Returns ``''`` when the phase
 * cannot be determined.
 *
 * Replaces the price heuristic behind the upload badge, which labelled every
 * unpriced X83 (an Angebotsaufforderung legitimately carries no prices) as
 * "X81" and every priced X84 as "X83".
 */
export function detectGAEBPhase(xmlString: string): string {
  if (!xmlString || !xmlString.trim()) return '';
  try {
    const doc = new DOMParser().parseFromString(xmlString, 'application/xml');
    if (doc.querySelector('parsererror')) return '';
    const dp = doc.querySelector('DP, DPType');
    const num = dp?.textContent?.trim().toLowerCase().replace(/^x/, '') ?? '';
    if (num && DP_TO_PHASE[num]) return DP_TO_PHASE[num];
    const ns = doc.documentElement?.namespaceURI ?? '';
    const dann = ns.match(/\/DA(\d{2})\//)?.[1] ?? '';
    if (dann && DP_TO_PHASE[dann]) return DP_TO_PHASE[dann];
    return '';
  } catch {
    return '';
  }
}

/**
 * Extract the project name (PrjInfo > NamePrj) from a GAEB DA XML string.
 *
 * Used to propose a name when the import target is a freshly created BOQ:
 * a Kalkulator answering someone else's Ausschreibung wants the new LV named
 * after the tender, not after an existing estimate.
 *
 * @param xmlString Raw XML content of the GAEB file.
 * @returns         The trimmed project name, or '' when absent/unparseable.
 */
export function parseGAEBProjectName(xmlString: string): string {
  if (!xmlString || !xmlString.trim()) return '';
  try {
    const doc = new DOMParser().parseFromString(xmlString, 'application/xml');
    if (doc.querySelector('parsererror')) return '';
    const namePrj = doc.querySelector('PrjInfo > NamePrj') ?? doc.querySelector('NamePrj');
    return namePrj?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  } catch {
    return '';
  }
}

/**
 * Read a GAEB XML File, parse it, and POST all positions to the BOQ API.
 *
 * The BoQCtgy hierarchy is preserved: every category on a position's
 * `sectionPath` is created (once) as a section header row via the sections
 * endpoint, nested under its parent category, and the position itself is
 * parented under its innermost category. Without this the LV arrived flat -
 * the import preview showed an "Abschnitt" per row while the editor and the
 * export summary reported zero sections.
 *
 * Positions are created sequentially to preserve ordinal ordering; a section
 * row is created right before its first child, so sort order mirrors the
 * document. Individual failures are collected in `errors` without aborting
 * the import; when a section cannot be created, its rows fall back to the
 * nearest successfully created ancestor instead of losing the hierarchy
 * entirely.
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
  const phase = detectGAEBPhase(xmlString);
  if (isGAEBSitePhase(phase)) {
    throw new Error(
      i18n.t('gaeb.site_phase_not_a_bill', {
        phase,
        defaultValue:
          'This is a GAEB {{phase}} file, not a bill of quantities. Open the bill it belongs to and use "GAEB X31 / X89" in its toolbar to read it.',
      }),
    );
  }
  const positions = parseGAEBXML(xmlString);

  let imported = 0;
  let sectionsCreated = 0;
  const errors: string[] = [];

  // Section rows created so far, keyed by their full dotted ordinal
  // ("01", "01.02", …). A failed create is remembered too, so a section is
  // attempted (and reported) once, not once per child row.
  const sectionIdByOrdinal = new Map<string, string>();
  const failedSectionOrdinals = new Set<string>();

  /**
   * Make sure every category on the path exists as a section row and return
   * the id of the innermost one that could be created (the new parent for
   * the current position). Categories are walked outermost-first so a child
   * section can reference its parent's id.
   */
  const ensureSectionChain = async (
    path: readonly GAEBSectionRef[],
  ): Promise<string | undefined> => {
    let parentId: string | undefined;
    for (const ref of path) {
      if (!ref.ordinal) continue;
      const existing = sectionIdByOrdinal.get(ref.ordinal);
      if (existing) {
        parentId = existing;
        continue;
      }
      if (failedSectionOrdinals.has(ref.ordinal)) continue;
      try {
        const created = await boqApi.addSection(boqId, {
          ordinal: ref.ordinal,
          description: ref.label || ref.ordinal,
          parent_id: parentId ?? null,
        });
        sectionIdByOrdinal.set(ref.ordinal, created.id);
        sectionsCreated++;
        parentId = created.id;
      } catch (err) {
        failedSectionOrdinals.add(ref.ordinal);
        const label = ref.label ? `${ref.ordinal} - ${truncateFinding(ref.label, 120)}` : ref.ordinal;
        const message = truncateFinding(err instanceof Error ? err.message : String(err), 300);
        errors.push(`Failed to create section "${label}": ${message}`);
        // Children of this category attach to the nearest created ancestor.
      }
    }
    return parentId;
  };

  for (const pos of positions) {
    // Skip positions that have no description and no unit (likely header artifacts)
    if (!pos.description && !pos.unit) {
      continue;
    }

    const parentId =
      pos.sectionPath && pos.sectionPath.length > 0
        ? await ensureSectionChain(pos.sectionPath)
        : undefined;

    const payload: CreatePositionData = {
      boq_id: boqId,
      ordinal: pos.ordinal || '000',
      description: pos.description || '(no description)',
      unit: pos.unit || 'pcs',
      quantity: pos.quantity,
      unit_rate: pos.unitRate,
      classification: {},
      ...(parentId ? { parent_id: parentId } : {}),
    };

    try {
      await boqApi.addPosition(payload);
      imported++;
    } catch (err) {
      // Keep findings screen-sized: a GAEB Langtext can carry tens of
      // thousands of characters (embedded graphics arrive as base64), and
      // echoing it into the error list once blew the layout to a
      // 337,468px scrollWidth. Identify the position, don't reprint it.
      const shortDesc = truncateFinding(pos.description, 120);
      const label = pos.ordinal ? `${pos.ordinal} - ${shortDesc}` : shortDesc;
      const message = truncateFinding(err instanceof Error ? err.message : String(err), 300);
      errors.push(`Failed to import position "${label}": ${message}`);
    }
  }

  return { imported, sectionsCreated, errors };
}
