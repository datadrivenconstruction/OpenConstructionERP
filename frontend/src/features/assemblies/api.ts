import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

export interface AssemblyComponent {
  id: string;
  assembly_id: string;
  cost_item_id: string | null;
  description: string;
  factor: number;
  quantity: number;
  unit: string;
  unit_cost: number;
  total: number;
  sort_order: number;
}

export interface Assembly {
  id: string;
  code: string;
  name: string;
  description: string;
  unit: string;
  category: string;
  classification: Record<string, string>;
  total_rate: number;
  currency: string;
  bid_factor: number;
  regional_factors: Record<string, string>;
  is_template: boolean;
  project_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AssemblyWithComponents extends Assembly {
  components: AssemblyComponent[];
}

export interface CreateAssemblyData {
  code: string;
  name: string;
  unit: string;
  category?: string;
  classification?: Record<string, string>;
  currency?: string;
  bid_factor?: number;
  project_id?: string;
}

export interface CreateComponentData {
  cost_item_id?: string;
  description: string;
  factor: number;
  quantity: number;
  unit: string;
  unit_cost: number;
}

export const assembliesApi = {
  list: (params?: { q?: string; category?: string; project_id?: string }) =>
    apiGet<Assembly[]>(`/v1/assemblies/?${new URLSearchParams(params as Record<string, string>)}`),
  get: (id: string) => apiGet<AssemblyWithComponents>(`/v1/assemblies/${id}`),
  create: (data: CreateAssemblyData) => apiPost<Assembly>('/v1/assemblies/', data),
  update: (id: string, data: Partial<CreateAssemblyData>) =>
    apiPatch<Assembly>(`/v1/assemblies/${id}`, data),
  delete: (id: string) => apiDelete(`/v1/assemblies/${id}`),
  addComponent: (assemblyId: string, data: CreateComponentData) =>
    apiPost<AssemblyComponent>(`/v1/assemblies/${assemblyId}/components`, data),
  updateComponent: (assemblyId: string, componentId: string, data: Partial<CreateComponentData>) =>
    apiPatch<AssemblyComponent>(`/v1/assemblies/${assemblyId}/components/${componentId}`, data),
  deleteComponent: (assemblyId: string, componentId: string) =>
    apiDelete(`/v1/assemblies/${assemblyId}/components/${componentId}`),
  applyToBoq: (assemblyId: string, boqId: string, quantity: number) =>
    apiPost(`/v1/assemblies/${assemblyId}/apply-to-boq`, { boq_id: boqId, quantity }),
};
