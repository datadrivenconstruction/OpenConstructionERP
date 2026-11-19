// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Staff API for the paper trail of a package: the imported bill file and
 * whether the bill still matches it, the award file (GAEB X86), documents sent
 * out with the package, and the files bidders uploaded.
 */

import { apiDelete, apiGet, apiPost, getAuthToken, triggerDownload } from '@/shared/lib/api';

export interface BillSource {
  id: string;
  format_id: string;
  variant: string;
  file_name: string;
  file_sha256: string;
  file_size: number;
  document_id: string | null;
  bill_sha256: string;
  line_count: number;
  imported_at: string | null;
}

export interface BillDifference {
  ordinal: string;
  /** ordinal, unit, quantity, text, removed or added. */
  field: string;
  was: string;
  now: string;
}

export interface ExchangeRuleResult {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  suggestion?: string | null;
}

export interface BillSourceState {
  source: BillSource | null;
  changed: boolean;
  differences: BillDifference[];
  awarded_bid_id: string | null;
  rule_results: ExchangeRuleResult[];
}

export interface PackageDocument {
  id: string;
  document_id: string;
  name: string;
  file_size: number;
  mime_type: string;
  category: string;
  revision_code?: string | null;
  added_at: string;
}

export interface BidFile {
  id: string;
  kind: 'x84' | 'offer_pdf' | 'attachment';
  file_name: string;
  file_size: number;
  sha256: string;
  uploaded_at: string;
  company_name: string;
  recipient_id: string;
  document_id: string | null;
}

export interface ProjectDocumentOption {
  id: string;
  name: string;
  category: string;
}

export function fetchBillSource(packageId: string): Promise<BillSourceState> {
  return apiGet(`/v1/tendering/packages/${packageId}/bill-source/`);
}

export function listPackageDocuments(packageId: string): Promise<PackageDocument[]> {
  return apiGet(`/v1/tendering/packages/${packageId}/documents/`);
}

export function attachPackageDocuments(packageId: string, documentIds: string[]): Promise<PackageDocument[]> {
  return apiPost(`/v1/tendering/packages/${packageId}/documents/`, { document_ids: documentIds });
}

export function detachPackageDocument(packageId: string, linkId: string): Promise<void> {
  return apiDelete(`/v1/tendering/packages/${packageId}/documents/${linkId}/`);
}

export function listBidFiles(packageId: string): Promise<BidFile[]> {
  return apiGet(`/v1/tendering/packages/${packageId}/bid-files/`);
}

export async function searchProjectDocuments(projectId: string, search: string): Promise<ProjectDocumentOption[]> {
  const params = new URLSearchParams({ project_id: projectId, limit: '50' });
  if (search.trim()) params.set('search', search.trim());
  const page = await apiGet<{ items: ProjectDocumentOption[] }>(`/v1/documents/?${params.toString()}`);
  return page.items ?? [];
}

/** Why an award file was refused, as a code the panel turns into a sentence. */
export class AwardExportError extends Error {
  constructor(
    public code: string,
    public differences: BillDifference[] = [],
    public ordinals: string[] = [],
  ) {
    super(code);
    this.name = 'AwardExportError';
  }
}

async function downloadAuthed(path: string, filename: string): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(`/api/v1/tendering/${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail ?? null;
    } catch {
      detail = null;
    }
    if (typeof detail === 'string') throw new AwardExportError(detail);
    if (detail && typeof detail === 'object' && 'code' in detail) {
      const d = detail as { code: string; differences?: BillDifference[]; ordinals?: string[] };
      throw new AwardExportError(d.code, d.differences ?? [], d.ordinals ?? []);
    }
    throw new AwardExportError('unknown');
  }
  triggerDownload(await res.blob(), filename);
}

/** Download the award file; the bid defaults to the accepted one. */
export function downloadAwardX86(packageId: string, packageName: string, bidId?: string | null): Promise<void> {
  const query = bidId ? `?bid_id=${encodeURIComponent(bidId)}` : '';
  const name = packageName.replace(/[^a-z0-9_-]+/gi, '_') || 'award';
  return downloadAuthed(`packages/${packageId}/export/gaeb-x86/${query}`, `${name}.X86`);
}

export function downloadBidFile(packageId: string, file: BidFile): Promise<void> {
  return downloadAuthed(`packages/${packageId}/bid-files/${file.id}/download/`, file.file_name);
}
