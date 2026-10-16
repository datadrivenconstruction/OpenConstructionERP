// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Document templates - one kind of document with a look of its own.
 *
 * The workspace appearance (/api/v1/document-appearance/) is the look every
 * PDF starts from. A document type may pin some of its fields on top of it: an
 * RFI with a different heading colour, a punch list without the letterhead
 * because it goes to site on plain paper. A field the type does not pin keeps
 * following the workspace, so changing the workspace look later still reaches
 * it.
 *
 * Each type lists the fields its generator actually reads. The pay application
 * prints its own fixed footer, so it offers no footer fields, and the server
 * refuses one rather than storing a knob that does nothing. Reading needs any
 * signed-in user, writing needs admin.
 */

import {
  API_BASE,
  activeLanguageTag,
  apiDelete,
  apiGet,
  apiPut,
  extractErrorMessageFromBody,
  getAuthToken,
} from '@/shared/lib/api';
import type { DocumentAppearance } from '@/features/property-dev/api';

/** Every field a type can pin, in the order the editor shows them. */
export const DOCUMENT_TYPE_FIELDS = [
  'show_letterhead',
  'logo_align',
  'accent_color',
  'footer_text',
  'footer_color',
  'show_page_numbers',
  'watermark_text',
] as const;

export type DocumentTypeField = (typeof DOCUMENT_TYPE_FIELDS)[number];

/** The fields that only change a document that prints a company letterhead. */
export const LETTERHEAD_FIELDS: readonly DocumentTypeField[] = [
  'show_letterhead',
  'logo_align',
  'accent_color',
];

/** What a type pins. A field left out follows the workspace look. */
export type DocumentTypeOverride = Partial<Pick<DocumentAppearance, DocumentTypeField>>;

export interface DocumentTypeEntry {
  key: string;
  /** English name, the fallback when the locale has no `label_key`. */
  label: string;
  label_key: string;
  /** The fields this type's generator reads. May name one this client does not know yet. */
  fields: string[];
  override: DocumentTypeOverride;
  /** The complete look the type prints with: the workspace look with `override` laid over it. */
  effective: DocumentAppearance;
  /**
   * The parts of the document a workspace may leave out (line items, notes,
   * signatures...). Empty for a type that prints a fixed form. Older servers
   * omit the field.
   */
  sections?: string[];
  /** The sections this workspace leaves out. Every other one prints. */
  hidden_sections?: string[];
}

export const DOCUMENT_TYPES_KEY = ['document-appearance', 'types'] as const;

export function isDocumentTypeField(field: string): field is DocumentTypeField {
  return (DOCUMENT_TYPE_FIELDS as readonly string[]).includes(field);
}

/** The configurable types, in the server's order. Types still reserved are left out. */
export function getDocumentTypes(): Promise<DocumentTypeEntry[]> {
  return apiGet<DocumentTypeEntry[]>('/v1/document-appearance/types/');
}

/**
 * Replace what a type pins. Admin only.
 *
 * Replace, not merge: the body is the whole override, so a field left out
 * stops being pinned. That is how the editor unpins a field, and why the body
 * is built from the pinned set rather than from the fields that changed.
 */
export function saveDocumentTypeOverride(
  key: string,
  override: DocumentTypeOverride,
): Promise<DocumentTypeEntry> {
  return apiPut<DocumentTypeEntry>(`/v1/document-appearance/types/${encodeURIComponent(key)}/`, override);
}

/**
 * Replace the sections a type leaves out of its documents. Admin only.
 *
 * Replace, not merge: a section not named here prints. The server refuses a
 * section the type does not have rather than storing a switch that does nothing.
 */
export function saveDocumentTypeSections(key: string, hidden: string[]): Promise<DocumentTypeEntry> {
  return apiPut<DocumentTypeEntry>(`/v1/document-appearance/types/${encodeURIComponent(key)}/sections/`, {
    hidden,
  });
}

/** Drop what a type pins, so it follows the workspace look again. Admin only. */
export function resetDocumentTypeOverride(key: string): Promise<DocumentTypeEntry> {
  return apiDelete<DocumentTypeEntry>(`/v1/document-appearance/types/${encodeURIComponent(key)}/`);
}

/**
 * Fetch one type's sample PDF, drawn from the saved settings on the sheet that
 * type prints on (the RFI on A4, the pay application on landscape Letter).
 *
 * Raw fetch for the same reason as `fetchSampleDocumentPdf`: a refusal answers
 * with a JSON problem, and a PDF viewer handed that body shows a broken file
 * instead of a message.
 */
export async function fetchDocumentTypeSamplePdf(key: string): Promise<Blob> {
  const lang = activeLanguageTag();
  const query = lang ? `?locale=${encodeURIComponent(lang)}` : '';
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: 'application/pdf' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(
    `${API_BASE}/v1/document-appearance/types/${encodeURIComponent(key)}/sample.pdf${query}`,
    { method: 'GET', headers },
  );
  if (!response.ok) {
    let detail = `Sample PDF failed (HTTP ${response.status})`;
    try {
      detail = extractErrorMessageFromBody(await response.json()) ?? detail;
    } catch {
      // Body was not JSON; keep the status-based message.
    }
    throw new Error(detail);
  }
  return response.blob();
}
