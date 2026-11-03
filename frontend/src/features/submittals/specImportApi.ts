import { apiGet, apiPost } from '@/shared/lib/api';

const BASE = '/v1/submittals/spec-imports';

export interface SpecImportStatus {
  id: string;
  status: 'uploaded' | 'parsed' | 'confirmed' | 'failed';
  section_count: number;
  pages_total: number;
  pages_done: number;
  error_code: string | null;
}

export interface SpecProposalItem {
  id: string;
  spec_section: string;
  section_title: string;
  kind: string;
  submittal_type: string;
  title: string;
  source_page: number;
  source_excerpt: string;
  confidence: number;
  decision: 'pending' | 'accepted' | 'rejected' | 'edited';
  submittal_id: string | null;
  duplicate: boolean;
}

export interface SpecImportProposals {
  import: SpecImportStatus & { document_id: string };
  items: SpecProposalItem[];
  warnings: { rule_id: string; spec_section: string; message: string; suggestion: string }[];
}

export interface SpecConfirmResult {
  created: { proposal_id: string; submittal_id: string; number: string }[];
  already_created: string[];
  skipped_duplicates: string[];
  status: string;
}

export function startSpecImport(projectId: string, documentId: string, useOcr = false): Promise<SpecImportStatus> {
  return apiPost<SpecImportStatus, { project_id: string; document_id: string; use_ocr: boolean }>(`${BASE}/`, {
    project_id: projectId,
    document_id: documentId,
    use_ocr: useOcr,
  });
}

export function getSpecImport(id: string): Promise<SpecImportStatus> {
  return apiGet<SpecImportStatus>(`${BASE}/${id}/`);
}

export function getSpecProposals(id: string): Promise<SpecImportProposals> {
  return apiGet<SpecImportProposals>(`${BASE}/${id}/proposals/`);
}

export function confirmSpecImport(
  id: string,
  acceptIds: string[],
  edits: Record<string, { title?: string }>,
): Promise<SpecConfirmResult> {
  return apiPost<SpecConfirmResult, { accept_ids: string[]; edits: Record<string, { title?: string }> }>(
    `${BASE}/${id}/confirm/`,
    { accept_ids: acceptIds, edits },
  );
}

/** Proposals grouped by section, in section order. */
export function groupBySection(items: SpecProposalItem[]): [string, SpecProposalItem[]][] {
  const groups = new Map<string, SpecProposalItem[]>();
  for (const it of items) {
    const list = groups.get(it.spec_section) ?? [];
    list.push(it);
    groups.set(it.spec_section, list);
  }
  return [...groups.entries()];
}

/** Proposals ticked by default: confident, not already created and not already in the register. */
export function defaultSelection(items: SpecProposalItem[], min = 0.7): Set<string> {
  return new Set(
    items.filter((i) => i.confidence >= min && !i.duplicate && i.submittal_id === null).map((i) => i.id),
  );
}
