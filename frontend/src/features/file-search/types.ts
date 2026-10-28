// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Wire types for the W3 file-search module.
 *
 * Mirrors backend/app/modules/file_search/schemas.py — keep in sync
 * when the backend changes shape.
 */

export type FileKind =
  | 'document'
  | 'photo'
  | 'sheet'
  | 'bim_model'
  | 'dwg_drawing'
  | 'takeoff'
  | 'report'
  | 'markup';

export type SearchMode = 'content' | 'filename';

export interface SearchHit {
  file_id: string;
  kind: FileKind | string;
  canonical_name: string;
  snippet: string;
  score: number;
  page_count: number | null;
}

export interface SearchResponse {
  project_id: string;
  q: string;
  mode: SearchMode;
  total: number;
  hits: SearchHit[];
}

export interface IndexFileRequest {
  project_id: string;
  file_kind: FileKind;
  file_id: string;
}

export interface IndexFileResponse {
  file_kind: string;
  file_id: string;
  indexed: boolean;
  ocr_engine: string;
  page_count: number | null;
  chars_extracted: number;
}

export interface ReindexResponse {
  project_id: string;
  started_at: string;
  queued: number;
  indexed: number;
  skipped: number;
  errors: number;
}
