// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Document layout API (/api/v1/doc-templates/layouts/). */

import { API_BASE, apiDelete, apiGet, apiPost, apiPut, fetchWithAuth } from '@/shared/lib/api';
import type { DocIssue } from '../api';

/** Per-language text: `{ en: "...", de: "..." }`. */
export type I18nText = Record<string, string>;

export type ConditionOp = 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'empty' | 'not_empty' | 'contains';

export interface BlockCondition {
  field: string;
  op: ConditionOp;
  value?: string;
}

export interface BlockStyle {
  align?: 'left' | 'center' | 'right' | 'justify';
  font_size?: number;
  space_before?: number;
  space_after?: number;
}

export interface TableColumn {
  id: string;
  label?: I18nText;
  width?: 'S' | 'M' | 'L';
  format?: string;
  expr?: string;
  hidden?: boolean;
}

export interface FieldEntry {
  field: string;
  label?: I18nText;
  omit_empty?: boolean;
  condition?: BlockCondition;
}

export interface TotalRow {
  field?: string;
  expr?: string;
  format?: string;
  label?: I18nText;
  condition?: BlockCondition;
}

export interface Signer {
  field: string;
  role?: I18nText;
}

export type BlockType =
  | 'section'
  | 'heading'
  | 'text'
  | 'notes'
  | 'fields'
  | 'table'
  | 'totals'
  | 'signatures'
  | 'image'
  | 'clause'
  | 'columns'
  | 'spacer'
  | 'page_break'
  | 'qr';

export interface LayoutBlock {
  id: string;
  type: BlockType;
  hidden?: boolean;
  condition?: BlockCondition;
  style?: BlockStyle;
  title?: I18nText;
  text?: I18nText;
  level?: 1 | 2;
  section?: string;
  fields?: FieldEntry[];
  layout?: 'pairs' | 'rows';
  collection?: string;
  columns?: TableColumn[] | LayoutBlock[][];
  group_by?: string;
  subtotals?: boolean;
  empty_text?: I18nText;
  rows?: TotalRow[];
  signers?: Signer[];
  source?: 'logo' | 'signature';
  width_mm?: number;
  data?: string;
  clause_id?: string;
  ratios?: number[];
  height_mm?: number;
  field?: string;
  size_mm?: number;
  caption?: boolean;
}

export interface FurnitureLine {
  text: I18nText;
  align?: 'left' | 'center' | 'right';
}

export interface PageSettings {
  size: 'A4' | 'Letter' | 'Legal';
  orientation: 'portrait' | 'landscape';
  margin_side_mm?: number;
  margin_top_mm?: number;
  margin_bottom_mm?: number;
  first_page_header?: boolean;
  page_numbers?: boolean;
}

export interface LayoutTemplate {
  schema: number;
  primary_locale: string;
  title: I18nText;
  subject: I18nText;
  show_subject: boolean;
  page: PageSettings;
  branding: { accent?: string; font?: 'serif'; letterhead?: boolean };
  watermark: Record<string, I18nText>;
  header: FurnitureLine[];
  footer: FurnitureLine[];
  body: LayoutBlock[];
}

export interface LayoutFieldInfo {
  path: string;
  type: string;
  group: string;
  label: string;
  sample: string;
}

export interface LayoutColumnInfo {
  id: string;
  label: string;
  heading: string;
  format: string;
  required: boolean;
  right: boolean;
}

export interface LayoutLocks {
  sections: Record<string, string>;
  columns: Record<string, Record<string, string>>;
  fields: Record<string, string>;
}

export interface LayoutSpecInfo {
  key: string;
  module: string;
  label: string;
  languages: string[];
  statuses: string[];
  block_types: BlockType[];
  column_child_types: BlockType[];
  condition_ops: ConditionOp[];
  fields: LayoutFieldInfo[];
  collections: { id: string; label: string; columns: LayoutColumnInfo[] }[];
  sections: { id: string; label: string; heading: string; required: boolean; builtin: boolean }[];
  locks: LayoutLocks;
  /** Fixed notes the country packs print in the legal zone; never editable here. */
  legal?: LegalBlock[];
  standard: LayoutTemplate;
}

export interface LegalBlock {
  id: string;
  country: string;
  text: string;
  source: string;
  when: string;
}

export interface LayoutVersion {
  id: string;
  number: number;
  action: 'publish' | 'restore' | 'reset' | 'import';
  note: string;
  author_name: string;
  created_at: string | null;
}

export interface LayoutVariant {
  variant: string;
  name: string;
  scope: string;
  is_default: boolean;
  published: boolean;
  has_draft: boolean;
}

export interface LayoutState {
  key: string;
  scope: string;
  variant: string;
  name: string;
  is_default: boolean;
  template: LayoutTemplate;
  published: LayoutTemplate | null;
  published_number: number | null;
  inherits: 'workspace' | 'standard' | null;
  has_draft: boolean;
  draft_updated_at: string | null;
  versions: LayoutVersion[];
  variants: LayoutVariant[];
  issues: DocIssue[];
}

export interface LayoutEditorData {
  spec: LayoutSpecInfo;
  state: LayoutState;
  can_edit: boolean;
}

export interface LayoutSummary {
  key: string;
  module: string;
  label: string;
  published: number;
  drafts: number;
  projects: number;
}

export interface LayoutChange {
  id: string;
  type: string;
  change: 'added' | 'removed' | 'changed' | 'moved';
  keys: string[];
}

export interface Clause {
  key: string;
  category: string;
  title: I18nText;
  text: I18nText;
}

/** Where a layout lives: the company default or one project's override, under one variant. */
export interface LayoutTarget {
  key: string;
  projectId?: string | null;
  variant: string;
  locale: string;
}

const base = '/v1/doc-templates/layouts';
const k = (key: string) => encodeURIComponent(key);

function query(target: LayoutTarget): string {
  const params = new URLSearchParams({ variant: target.variant, locale: target.locale });
  if (target.projectId) params.set('project_id', target.projectId);
  return params.toString();
}

export const listLayouts = () =>
  apiGet<{ items: LayoutSummary[]; total: number; can_edit: boolean }>(`${base}/`);
export const getLayout = (t: LayoutTarget) => apiGet<LayoutEditorData>(`${base}/${k(t.key)}?${query(t)}`);
export const saveLayoutDraft = (t: LayoutTarget, template: LayoutTemplate, name = '') =>
  apiPut<LayoutEditorData>(`${base}/${k(t.key)}/draft?${query(t)}`, { template, name });
export const discardLayoutDraft = (t: LayoutTarget) =>
  apiDelete<LayoutEditorData>(`${base}/${k(t.key)}/draft?${query(t)}`);
export const publishLayout = (t: LayoutTarget, note = '') =>
  apiPost<LayoutEditorData>(`${base}/${k(t.key)}/publish?${query(t)}`, { note });
export const resetLayout = (t: LayoutTarget) => apiPost<LayoutEditorData>(`${base}/${k(t.key)}/reset?${query(t)}`, {});
export const makeLayoutDefault = (t: LayoutTarget) =>
  apiPost<LayoutEditorData>(`${base}/${k(t.key)}/default?${query(t)}`, {});
export const deleteLayoutVariant = (t: LayoutTarget) =>
  apiDelete<LayoutEditorData>(`${base}/${k(t.key)}/variant?${query(t)}`);
export const restoreLayoutVersion = (t: LayoutTarget, versionId: string) =>
  apiPost<LayoutEditorData>(`${base}/${k(t.key)}/versions/${versionId}/restore?${query(t)}`, {});
export const getLayoutVersion = (key: string, versionId: string) =>
  apiGet<{ template: LayoutTemplate }>(`${base}/${k(key)}/versions/${versionId}`);
export const diffLayoutVersion = (key: string, versionId: string, against?: string) =>
  apiGet<{ changes: LayoutChange[] }>(
    `${base}/${k(key)}/versions/${versionId}/diff${against ? `?against=${encodeURIComponent(against)}` : ''}`,
  );
export const exportLayout = (t: LayoutTarget) => apiGet<Record<string, unknown>>(`${base}/${k(t.key)}/export?${query(t)}`);
export const importLayout = (t: LayoutTarget, file: Record<string, unknown>) =>
  apiPost<LayoutEditorData>(`${base}/${k(t.key)}/import?${query(t)}`, file);
export const listLayoutRecords = (key: string) =>
  apiGet<{ items: { id: string; label: string }[]; total: number }>(`${base}/${k(key)}/records`);
export const getLayoutValues = (key: string, locale: string, recordId: string | null) =>
  apiGet<{ values: Record<string, string>; status: string; rows: Record<string, number>; issues?: DocIssue[] }>(
    `${base}/${k(key)}/values?locale=${encodeURIComponent(locale)}${recordId ? `&record_id=${encodeURIComponent(recordId)}` : ''}`,
  );
export const listClauses = () => apiGet<{ items: Clause[]; total: number }>(`${base}/clauses`);
export const saveClause = (key: string, clause: Omit<Clause, 'key'>) =>
  apiPut<Clause>(`${base}/clauses/${encodeURIComponent(key)}`, clause);
export const deleteClause = (key: string) => apiDelete(`${base}/clauses/${encodeURIComponent(key)}`);

/** Server-rendered PDF of an unsaved template, on a record or on sample data. */
export async function fetchLayoutPreview(
  key: string,
  locale: string,
  template: LayoutTemplate,
  recordId: string | null,
  signal?: AbortSignal,
): Promise<Blob> {
  const r = await fetchWithAuth(`${API_BASE}${base}/${k(key)}/preview?locale=${encodeURIComponent(locale)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template, record_id: recordId }),
    signal,
  });
  if (!r.ok) throw new Error(`preview ${r.status}`);
  return r.blob();
}
