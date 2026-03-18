import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

export interface Project {
  id: string;
  name: string;
  description: string;
  region: string;
  classification_standard: string;
  currency: string;
  locale: string;
  validation_rule_sets: string[];
  status: string;
  owner_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateProjectData {
  name: string;
  description?: string;
  region?: string;
  classification_standard?: string;
  currency?: string;
  locale?: string;
}

export const projectsApi = {
  list: () => apiGet<Project[]>('/v1/projects/'),
  get: (id: string) => apiGet<Project>(`/v1/projects/${id}`),
  create: (data: CreateProjectData) => apiPost<Project>('/v1/projects/', data),
  update: (id: string, data: Partial<CreateProjectData>) =>
    apiPatch<Project>(`/v1/projects/${id}`, data),
  archive: (id: string) => apiDelete(`/v1/projects/${id}`),
};
