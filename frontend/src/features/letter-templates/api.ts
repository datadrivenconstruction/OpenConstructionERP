// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Letter templates API (/api/v1/letter-templates/). */

import { API_BASE, apiDelete, apiGet, apiPut, fetchWithAuth } from '@/shared/lib/api';
import type { LetterIssue, LetterPlaceholder, LetterText } from './letterRules';

export interface LetterTemplateSummary {
  key: string;
  module: string;
  kind: 'pdf' | 'email';
  languages: string[];
  customised_languages: string[];
}

export interface ResolvedLetterTemplate {
  key: string;
  module: string;
  kind: 'pdf' | 'email';
  language: string;
  source: 'project' | 'company' | 'default';
  text: LetterText;
  default: LetterText;
  placeholders: LetterPlaceholder[];
  issues: LetterIssue[];
}

export function listLetterTemplates(): Promise<LetterTemplateSummary[]> {
  return apiGet<LetterTemplateSummary[]>(`/v1/letter-templates/`);
}

export function getLetterTemplate(
  key: string,
  opts: { language?: string; projectId?: string } = {},
): Promise<ResolvedLetterTemplate> {
  const q = new URLSearchParams();
  if (opts.language) q.set('language', opts.language);
  if (opts.projectId) q.set('project_id', opts.projectId);
  const qs = q.toString();
  return apiGet<ResolvedLetterTemplate>(`/v1/letter-templates/${encodeURIComponent(key)}${qs ? `?${qs}` : ''}`);
}

export function saveLetterTemplate(
  key: string,
  body: LetterText & { language: string; project_id?: string | null },
): Promise<ResolvedLetterTemplate> {
  return apiPut<ResolvedLetterTemplate>(`/v1/letter-templates/${encodeURIComponent(key)}`, body);
}

export function resetLetterTemplate(key: string, language: string): Promise<void> {
  return apiDelete(`/v1/letter-templates/${encodeURIComponent(key)}?language=${encodeURIComponent(language)}`);
}

/** Sample letter from unsaved text: a PDF, or the email as HTML. */
export async function fetchLetterPreview(key: string, language: string, text: LetterText): Promise<Blob | null> {
  const r = await fetchWithAuth(`${API_BASE}/v1/letter-templates/${encodeURIComponent(key)}/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...text, language }),
  });
  if (!r.ok || r.status === 204) return null;
  return r.blob();
}

/** Award letter or rejection notice with one-off wording. */
export async function downloadTenderLetter(
  packageId: string,
  bidId: string,
  kind: 'award-letter' | 'rejection-letter',
  text: LetterText,
): Promise<Blob | null> {
  const r = await fetchWithAuth(`${API_BASE}/v1/tendering/packages/${packageId}/bids/${bidId}/${kind}/pdf/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(text),
  });
  return r.ok ? r.blob() : null;
}
