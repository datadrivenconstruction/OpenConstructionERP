// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Document assistant: typed client for /api/v1/doc-assistant/*.

import { apiGet, apiPost } from '@/shared/lib/api';

export type SourceKind =
  | 'specification'
  | 'drawing'
  | 'contract'
  | 'document'
  | 'rfi'
  | 'submittal'
  | 'correspondence'
  | 'minutes';

export const SOURCE_KINDS: SourceKind[] = [
  'specification',
  'drawing',
  'contract',
  'rfi',
  'submittal',
  'correspondence',
  'minutes',
  'document',
];

export interface Citation {
  ref: number;
  passage_id: string;
  source_kind: SourceKind;
  source_id: string;
  document_id: string | null;
  title: string;
  revision: string | null;
  page: number | null;
  sheet_number: string | null;
  section: string | null;
  snippet: string;
  deep_link: string;
  score: number;
}

export interface Claim {
  text: string;
  citations: number[];
  quote?: string | null;
  quoted: boolean;
}

export interface AskResponse {
  status: 'answered' | 'not_found' | 'no_documents';
  mode: 'generated' | 'extractive' | 'none';
  question: string;
  locale: string;
  answer: string;
  confidence: number;
  threshold: number;
  claims: Claim[];
  citations: Citation[];
  nearest: Citation[];
  searched_passages: number;
  tokens: number;
}

export interface SavedAnswer {
  id: string;
  project_id: string;
  question: string;
  answer: string;
  citations: Citation[];
  confidence: number;
  target_kind: 'note' | 'rfi';
  target_id: string | null;
  validation: { status: string; findings: { rule_id: string; severity: string; message: string }[] };
  created_at: string;
}

export const docAssistantApi = {
  ask: (body: { project_id: string; question: string; locale: string; kinds: SourceKind[] }) =>
    apiPost<AskResponse>('/v1/doc-assistant/ask', body),
  save: (body: {
    project_id: string;
    question: string;
    answer: string;
    claims: Claim[];
    citations: Citation[];
    confidence: number;
    locale: string;
    target: 'note' | 'rfi';
  }) => apiPost<SavedAnswer>('/v1/doc-assistant/saved', body),
  listSaved: (projectId: string) =>
    apiGet<{ items: SavedAnswer[]; total: number }>(`/v1/doc-assistant/saved?project_id=${encodeURIComponent(projectId)}`),
};

/** Where a citation points, as short parts: revision, sheet, page, section. */
export function citationLocation(c: Citation): string[] {
  const parts: string[] = [];
  if (c.revision) parts.push(`rev ${c.revision}`);
  if (c.sheet_number) parts.push(c.sheet_number);
  if (c.page) parts.push(`p. ${c.page}`);
  if (c.section) parts.push(c.section);
  return parts;
}

/** A deep link the router can open; only in-app paths are followed. */
export function safeDeepLink(c: Citation): string | null {
  return c.deep_link && c.deep_link.startsWith('/') && !c.deep_link.startsWith('//') ? c.deep_link : null;
}
