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
  owner_id: string | null;
  is_active: boolean;
  component_count: number;
  usage_count: number;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface AssemblyExport {
  code: string;
  name: string;
  description: string;
  unit: string;
  category: string;
  classification: Record<string, string>;
  currency: string;
  bid_factor: number;
  regional_factors: Record<string, string>;
  tags: string[];
  components: Array<{
    description: string;
    factor: number;
    quantity: number;
    unit: string;
    unit_cost: number;
    sort_order: number;
  }>;
}

export interface AssemblySearchResponse {
  items: Assembly[];
  total: number;
  limit: number;
  offset: number;
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

export interface AIGenerateRequest {
  description: string;
  region?: string;
  unit?: string;
}

export interface AIGeneratedComponent {
  name: string;
  code: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
  type: string;
  sort_order: number;
  cost_item_id?: string;
}

export interface AIGeneratedAssembly {
  name: string;
  code: string;
  unit: string;
  category: string;
  components: AIGeneratedComponent[];
  total_rate: number;
  source_items_count: number;
  confidence: number;
  description: string;
  region: string;
}

export const assembliesApi = {
  list: (params?: Record<string, string>) =>
    apiGet<AssemblySearchResponse>(`/v1/assemblies/?${new URLSearchParams(params)}`),
  get: (id: string) => apiGet<AssemblyWithComponents>(`/v1/assemblies/${id}`),
  create: (data: CreateAssemblyData) => apiPost<Assembly>('/v1/assemblies/', data),
  update: (id: string, data: Partial<CreateAssemblyData>) =>
    apiPatch<Assembly>(`/v1/assemblies/${id}`, data),
  delete: (id: string) => apiDelete(`/v1/assemblies/${id}`),
  addComponent: (assemblyId: string, data: CreateComponentData) =>
    apiPost<AssemblyComponent>(`/v1/assemblies/${assemblyId}/components/`, data),
  updateComponent: (assemblyId: string, componentId: string, data: Partial<CreateComponentData>) =>
    apiPatch<AssemblyComponent>(`/v1/assemblies/${assemblyId}/components/${componentId}`, data),
  deleteComponent: (assemblyId: string, componentId: string) =>
    apiDelete(`/v1/assemblies/${assemblyId}/components/${componentId}`),
  applyToBoq: (assemblyId: string, boqId: string, quantity: number) =>
    apiPost(`/v1/assemblies/${assemblyId}/apply-to-boq/`, { boq_id: boqId, quantity }),
  aiGenerate: (data: AIGenerateRequest) =>
    apiPost<AIGeneratedAssembly>('/v1/assemblies/ai-generate/', data),
  reorderComponents: (assemblyId: string, componentIds: string[]) =>
    apiPost(`/v1/assemblies/${assemblyId}/reorder-components/`, { component_ids: componentIds }),
  exportAssembly: (assemblyId: string) =>
    apiGet<AssemblyExport>(`/v1/assemblies/${assemblyId}/export/`),
  importAssembly: (data: AssemblyExport) =>
    apiPost<Assembly>('/v1/assemblies/import/', { assembly: data }),
  updateTags: (assemblyId: string, tags: string[]) =>
    apiPatch<Assembly>(`/v1/assemblies/${assemblyId}/tags/`, { tags }),
};
