import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

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
}

export const boqApi = {
  list: (projectId: string) => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${projectId}`),
  get: (boqId: string) => apiGet<BOQWithPositions>(`/v1/boq/boqs/${boqId}`),
  create: (data: CreateBOQData) => apiPost<BOQ>('/v1/boq/boqs/', data),
  addPosition: (data: CreatePositionData) =>
    apiPost<Position>(`/v1/boq/boqs/${data.boq_id}/positions`, data),
  updatePosition: (posId: string, data: UpdatePositionData) =>
    apiPatch<Position>(`/v1/boq/positions/${posId}`, data),
  deletePosition: (posId: string) => apiDelete(`/v1/boq/positions/${posId}`),
};
