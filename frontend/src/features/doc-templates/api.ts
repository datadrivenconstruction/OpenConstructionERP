// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Documents & templates API (/api/v1/doc-templates/). */

import { API_BASE, apiDelete, apiGet, apiPost, apiPut, fetchWithAuth, type Page } from '@/shared/lib/api';

export type Channel = 'pdf' | 'email';
export type WordingStatus = 'default' | 'custom' | 'draft' | 'error';

export interface DocIssue {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  block: string;
  params: Record<string, string>;
}

export interface DocKindSummary {
  key: string;
  channel: Channel;
  module: string;
  label: string;
  status: WordingStatus;
  languages: string[];
  builtin_languages: string[];
  last_published_at: string | null;
  last_published_by: string;
  error_rules: string[];
}

export interface DocKindList {
  items: DocKindSummary[];
  total: number;
  can_edit: boolean;
  email_enabled: boolean;
}

export interface MergeFieldInfo {
  path: string;
  type: string;
  group: string;
  sample: string;
}

export interface DocVersion {
  id: string;
  number: number;
  action: 'publish' | 'restore' | 'reset';
  note: string;
  author_name: string;
  created_at: string;
  is_published: boolean;
}

export interface TemplateOptions {
  font: 'sans' | 'serif';
  signature_image: string;
}

export interface LegalBlockInfo {
  id: string;
  country: string;
  text: string;
  source: string;
  when: string;
}

export interface EditorState {
  key: string;
  channel: Channel;
  module: string;
  label: string;
  locale: string;
  blocks: string[];
  required_blocks: string[];
  text: Record<string, string>;
  default_text: Record<string, string>;
  published_text: Record<string, string> | null;
  has_draft: boolean;
  has_translation: boolean;
  builtin_language: boolean;
  primary_locale: string | null;
  options: TemplateOptions;
  fields: MergeFieldInfo[];
  versions: DocVersion[];
  issues: DocIssue[];
  legal_blocks: LegalBlockInfo[];
  has_records: boolean;
}

export interface EmailPreview {
  subject: string;
  html: string;
  issues: DocIssue[];
}

export interface DocManager {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  is_manager: boolean;
}

const base = '/v1/doc-templates';
const k = (key: string) => encodeURIComponent(key);

export const listDocKinds = () => apiGet<DocKindList>(`${base}/`);
export const getEditor = (key: string, locale: string) =>
  apiGet<EditorState>(`${base}/${k(key)}?locale=${encodeURIComponent(locale)}`);
export const saveDraft = (key: string, locale: string, blocks: Record<string, string>, options?: TemplateOptions) =>
  apiPut<EditorState>(`${base}/${k(key)}/draft?locale=${encodeURIComponent(locale)}`, { blocks, options });
export const discardDraft = (key: string, locale: string) =>
  apiDelete(`${base}/${k(key)}/draft?locale=${encodeURIComponent(locale)}`);
export const publishTemplate = (key: string, locale: string, note = '') =>
  apiPost<EditorState>(`${base}/${k(key)}/publish?locale=${encodeURIComponent(locale)}`, { note });
export const restoreVersion = (key: string, locale: string, versionId: string) =>
  apiPost<EditorState>(`${base}/${k(key)}/versions/${versionId}/restore?locale=${encodeURIComponent(locale)}`, {});
export const resetTemplate = (key: string, locale: string) =>
  apiPost<EditorState>(`${base}/${k(key)}/reset?locale=${encodeURIComponent(locale)}`, {});
export const listRecords = (key: string) => apiGet<Page<{ id: string; label: string }>>(`${base}/${k(key)}/records`);
export const sendTest = (key: string, locale: string, blocks: Record<string, string>) =>
  apiPost<{ sent: boolean; to: string; detail: string }>(
    `${base}/${k(key)}/test-send?locale=${encodeURIComponent(locale)}`,
    { blocks },
  );
export const listManagers = () => apiGet<Page<DocManager>>(`${base}/managers`);
export const setManager = (userId: string, isManager: boolean) =>
  apiPut<DocManager>(`${base}/managers/${userId}`, { is_manager: isManager });

/** Server preview of unsaved text: a PDF blob, or the email subject and HTML. */
export async function fetchPreview(
  key: string,
  locale: string,
  blocks: Record<string, string>,
  options: TemplateOptions | undefined,
  recordId: string | null,
  signal?: AbortSignal,
): Promise<{ pdf: Blob } | { email: EmailPreview }> {
  const r = await fetchWithAuth(`${API_BASE}${base}/${k(key)}/preview?locale=${encodeURIComponent(locale)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ blocks, options, record_id: recordId }),
    signal,
  });
  if (!r.ok) throw new Error(`preview ${r.status}`);
  if ((r.headers.get('content-type') ?? '').includes('application/pdf')) return { pdf: await r.blob() };
  return { email: (await r.json()) as EmailPreview };
}
