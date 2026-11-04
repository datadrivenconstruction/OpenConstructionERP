// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Lessons learned API. Backend: /api/v1/lessons_learned. */
import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

export type Impact = 'low' | 'medium' | 'high';
export type LessonStatus = 'draft' | 'confirmed';

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
}

export interface Lesson {
  id: string;
  project_id: string;
  title: string;
  description: string;
  recommendation: string;
  trade: string;
  cost_code: string;
  risk_category: string;
  impact: Impact;
  status: LessonStatus;
  confirmed_at: string | null;
  findings: Finding[];
}

export interface LessonInput {
  project_id: string;
  title: string;
  description: string;
  recommendation: string;
  trade: string;
  cost_code: string;
  risk_category: string;
  impact: Impact;
}

export interface SeenLesson {
  id: string;
  project_id: string;
  title: string;
  recommendation: string;
  impact: Impact;
  matched: string[];
}

export interface SeenResult {
  projects: number;
  lessons: number;
  top: SeenLesson[];
}

export interface SeenQuery {
  projectId?: string;
  trade?: string;
  costCode?: string;
  riskCategory?: string;
}

const BASE = '/v1/lessons_learned';

export const lessonsApi = {
  list: (projectId?: string) =>
    apiGet<Lesson[]>(`${BASE}/${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`),
  create: (body: LessonInput) => apiPost<Lesson, LessonInput>(`${BASE}/`, body),
  confirm: (id: string) => apiPost<Lesson>(`${BASE}/${id}/confirm`),
  update: (id: string, body: Partial<LessonInput>) => apiPatch<Lesson, Partial<LessonInput>>(`${BASE}/${id}`, body),
  remove: (id: string) => apiDelete(`${BASE}/${id}`),
  seen: (q: SeenQuery) => {
    const p = new URLSearchParams();
    if (q.projectId) p.set('project_id', q.projectId);
    if (q.trade) p.set('trade', q.trade);
    if (q.costCode) p.set('cost_code', q.costCode);
    if (q.riskCategory) p.set('risk_category', q.riskCategory);
    const qs = p.toString();
    return apiGet<SeenResult>(`${BASE}/seen${qs ? `?${qs}` : ''}`);
  },
};
