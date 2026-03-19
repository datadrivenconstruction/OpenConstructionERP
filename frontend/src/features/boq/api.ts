import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Core BOQ types ──────────────────────────────────────────────────── */

export interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Position {
  id: string;
  boq_id: string;
  parent_id: string | null;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
  classification: Record<string, string>;
  source: string;
  confidence: number | null;
  validation_status: string;
  sort_order: number;
  metadata: Record<string, unknown>;
}

export interface BOQWithPositions extends BOQ {
  positions: Position[];
  grand_total: number;
}

/* ── Markup types ────────────────────────────────────────────────────── */

export interface Markup {
  id: string;
  boq_id: string;
  name: string;
  percentage: number;
  sort_order: number;
}

export interface MarkupsResponse {
  markups: Markup[];
}

export interface CreateMarkupData {
  name: string;
  percentage: number;
}

export interface UpdateMarkupData {
  name?: string;
  percentage?: number;
}

/* ── Create / Update payloads ────────────────────────────────────────── */

export interface CreateBOQData {
  project_id: string;
  name: string;
  description?: string;
}

export interface CreatePositionData {
  boq_id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  classification?: Record<string, string>;
  parent_id?: string;
}

export interface UpdatePositionData {
  ordinal?: string;
  description?: string;
  unit?: string;
  quantity?: number;
  unit_rate?: number;
  classification?: Record<string, string>;
  parent_id?: string | null;
}

/* ── Section helpers (used on the frontend to group positions) ────── */

/** A section is a position with no unit (acts as a group header). */
export function isSection(pos: Position): boolean {
  return !pos.unit || pos.unit.trim() === '';
}

/**
 * Organizes a flat positions list into sections with children.
 * A section is any position where `unit` is empty.
 * Positions with a `parent_id` pointing to a section go under that section.
 * Positions without a parent that are not sections go into an "Ungrouped" virtual bucket.
 */
export interface SectionGroup {
  section: Position;
  children: Position[];
  subtotal: number;
}

export function groupPositionsIntoSections(positions: Position[]): {
  sections: SectionGroup[];
  ungrouped: Position[];
} {
  const sections: SectionGroup[] = [];
  const ungrouped: Position[] = [];
  const sectionMap = new Map<string, SectionGroup>();

  // First pass: identify sections
  const sortedPositions = [...positions].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
    return a.ordinal.localeCompare(b.ordinal, undefined, { numeric: true });
  });

  for (const pos of sortedPositions) {
    if (isSection(pos)) {
      const group: SectionGroup = { section: pos, children: [], subtotal: 0 };
      sectionMap.set(pos.id, group);
      sections.push(group);
    }
  }

  // Second pass: assign children to sections
  for (const pos of sortedPositions) {
    if (isSection(pos)) continue;

    if (pos.parent_id && sectionMap.has(pos.parent_id)) {
      const group = sectionMap.get(pos.parent_id)!;
      group.children.push(pos);
      group.subtotal += pos.total;
    } else {
      ungrouped.push(pos);
    }
  }

  return { sections, ungrouped };
}

/* ── Activity types ──────────────────────────────────────────────────── */

export type ActivityAction =
  | 'position_added'
  | 'position_updated'
  | 'position_deleted'
  | 'quantity_updated'
  | 'rate_updated'
  | 'section_added'
  | 'section_deleted'
  | 'validation_run'
  | 'excel_imported'
  | 'csv_imported'
  | 'boq_created'
  | 'template_applied'
  | 'markup_added'
  | 'markup_updated'
  | 'status_changed';

export interface ActivityEntry {
  id: string;
  boq_id: string;
  action: ActivityAction;
  description: string;
  details: Record<string, unknown>;
  created_at: string;
  user_name?: string;
}

export interface ActivityResponse {
  activities: ActivityEntry[];
  total: number;
}

/* ── API client ──────────────────────────────────────────────────────── */

export const boqApi = {
  /* BOQ CRUD */
  list: (projectId: string) => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${projectId}`),
  get: (boqId: string) => apiGet<BOQWithPositions>(`/v1/boq/boqs/${boqId}`),
  create: (data: CreateBOQData) => apiPost<BOQ>('/v1/boq/boqs/', data),

  /* Duplicate */
  duplicateBoq: (boqId: string) => apiPost<BOQ>(`/v1/boq/boqs/${boqId}/duplicate`, {}),
  duplicatePosition: (posId: string) =>
    apiPost<Position>(`/v1/boq/positions/${posId}/duplicate`, {}),

  /* Position CRUD */
  addPosition: (data: CreatePositionData) =>
    apiPost<Position>(`/v1/boq/boqs/${data.boq_id}/positions`, data),
  updatePosition: (posId: string, data: UpdatePositionData) =>
    apiPatch<Position>(`/v1/boq/positions/${posId}`, data),
  deletePosition: (posId: string) => apiDelete(`/v1/boq/positions/${posId}`),

  /* Markups */
  getMarkups: (boqId: string) => apiGet<MarkupsResponse>(`/v1/boq/boqs/${boqId}/markups`),
  addMarkup: (boqId: string, data: CreateMarkupData) =>
    apiPost<Markup>(`/v1/boq/boqs/${boqId}/markups`, data),
  updateMarkup: (markupId: string, data: UpdateMarkupData) =>
    apiPatch<Markup>(`/v1/boq/markups/${markupId}`, data),
  deleteMarkup: (markupId: string) => apiDelete(`/v1/boq/markups/${markupId}`),

  /* Activity */
  getActivity: (boqId: string) =>
    apiGet<ActivityResponse>(`/v1/boq/boqs/${boqId}/activity`),
};
