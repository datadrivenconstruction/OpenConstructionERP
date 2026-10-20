// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Company profile - the letterhead printed on generated documents.
 *
 * A record of its own, apart from the workspace brand (/api/v1/branding/). The
 * brand is what the sidebar and the login page show and is served to anonymous
 * callers; the letterhead carries a registered address and tax identifiers, so
 * the server keeps it behind sign-in. Reading needs any signed-in user,
 * writing needs admin.
 *
 * Every field is free text on purpose: address order and the identifiers a
 * firm must print differ by country, so the firm writes the lines exactly as
 * they appear on its paper and the PDF prints them verbatim.
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

/** The stored letterhead. Always complete; an unset field is `""`. */
export interface CompanyProfile {
  document_logo_data_url: string;
  /** PNG copy of an SVG logo, made in the browser; PDFs print this. `""` when unset. */
  document_logo_png_data_url: string;
  legal_name: string;
  /** Up to three lines, newline separated. */
  address: string;
  /** Whatever registration and licence numbers the firm prints, as one line. */
  registration_line: string;
  phone: string;
  email: string;
  website: string;
}

/** The text fields the details form edits, in the order it shows them. */
export const COMPANY_TEXT_FIELDS = [
  'legal_name',
  'address',
  'registration_line',
  'phone',
  'email',
  'website',
] as const;

export type CompanyTextField = (typeof COMPANY_TEXT_FIELDS)[number];

/**
 * The caps the server's sanitiser enforces, served from the same constants, so
 * a form built from this cannot accept text the server would quietly trim or a
 * file type it would quietly drop.
 */
export interface CompanyProfileOptions {
  max_lengths: Partial<Record<CompanyTextField, number>>;
  max_address_lines: number;
  max_logo_data_url_chars: number;
  logo_mime_types: string[];
}

export const COMPANY_PROFILE_KEY = ['company-profile'] as const;
export const COMPANY_PROFILE_OPTIONS_KEY = ['company-profile', 'options'] as const;

export function getCompanyProfile(): Promise<CompanyProfile> {
  return apiGet<CompanyProfile>('/v1/company-profile/');
}

export function getCompanyProfileOptions(): Promise<CompanyProfileOptions> {
  return apiGet<CompanyProfileOptions>('/v1/company-profile/options/');
}

/**
 * Save the fields that changed. Admin only.
 *
 * The server merges the patch over what is stored: a field left out is kept
 * and `""` clears it, so the logo and the text form can be saved separately.
 */
export function saveCompanyProfile(patch: Partial<CompanyProfile>): Promise<CompanyProfile> {
  return apiPut<CompanyProfile>('/v1/company-profile/', patch);
}

/** Clear the whole letterhead. Admin only. */
export function resetCompanyProfile(): Promise<CompanyProfile> {
  return apiDelete<CompanyProfile>('/v1/company-profile/');
}

/**
 * Whether a printed document carries a letterhead, by the server's own rule:
 * only a legal name or a document logo switches it on. An address or a phone
 * number alone does not, because contact details with no name above them do
 * not say whose they are. The app logo fallback does not count either.
 */
export function hasLetterhead(profile: Pick<CompanyProfile, 'legal_name' | 'document_logo_data_url'>): boolean {
  return Boolean(profile.legal_name.trim() || profile.document_logo_data_url.trim());
}

/**
 * Fetch the sample PDF, rendered by the server from the saved profile and the
 * saved document appearance.
 *
 * Not through apiGet, which parses JSON. The failure branch is the part worth
 * keeping: a refusal answers with a JSON problem, and handing that body to a
 * PDF viewer shows a broken document instead of a message the user can act on.
 * The UI language travels as ?locale= because this fetch does not carry the
 * Accept-Language header apiGet attaches.
 */
export async function fetchSampleDocumentPdf(): Promise<Blob> {
  const lang = activeLanguageTag();
  const query = lang ? `?locale=${encodeURIComponent(lang)}` : '';
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: 'application/pdf' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}/v1/document-appearance/sample.pdf${query}`, {
    method: 'GET',
    headers,
  });
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
