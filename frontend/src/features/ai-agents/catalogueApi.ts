// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Project agent catalogue: typed client for /api/v1/ai-agents/catalogue/*.

import { apiGet, apiPost, apiPut } from '@/shared/lib/api';

export type CatalogueAgentName = 'rfi_drafter' | 'daily_reporter' | 'clause_reviewer' | 'submittal_checker';

export interface CatalogueInput {
  key: string;
  kind: 'text' | 'date' | 'record';
  required: boolean;
  record: string | null;
}

export interface CatalogueAgent {
  name: CatalogueAgentName;
  draft_kind: string;
  display_name: string;
  tagline: string;
  icon: string;
  entry_surface: 'rfi' | 'daily_report' | 'contract' | 'submittal';
  inputs: CatalogueInput[];
  tools: string[];
  read_only_tools: boolean;
  enabled: boolean;
  config: Record<string, unknown> & { review_after_days?: number };
  max_tokens_per_run: number;
}

export interface CatalogueState {
  project_id: string;
  halted: boolean;
  halt_reason: string;
  agents: CatalogueAgent[];
}

export interface AgentDraftSource {
  title?: string;
  label?: string;
  kind?: string;
  id?: string;
  revision?: string | null;
  page?: number | null;
  sheet_number?: string | null;
  section?: string | null;
  deep_link?: string;
}

export interface AgentDraft {
  id: string;
  project_id: string;
  run_id: string | null;
  agent_name: CatalogueAgentName;
  draft_kind: string;
  title: string;
  payload: Record<string, unknown>;
  confidence: number;
  sources: AgentDraftSource[];
  status: 'pending' | 'accepted' | 'rejected';
  reviewed_at: string | null;
  review_note: string | null;
  applied_record_id: string | null;
  created_at: string | null;
}

export interface CatalogueRun {
  id: string;
  agent_name: string;
  status: string;
  failure_reason: string | null;
  trigger_source: string;
  total_tokens: number;
  iterations: number;
  final_output: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface DraftFinding {
  rule_id: string;
  severity: string;
  message: string;
  draft_id: string | null;
}

export const catalogueApi = {
  get: (projectId: string) => apiGet<CatalogueState>(`/v1/ai-agents/catalogue/projects/${encodeURIComponent(projectId)}`),
  configure: (
    projectId: string,
    agent: CatalogueAgentName,
    body: { enabled?: boolean; config?: Record<string, unknown>; max_tokens_per_run?: number },
  ) => apiPut<CatalogueState>(`/v1/ai-agents/catalogue/projects/${encodeURIComponent(projectId)}/agents/${agent}`, body),
  halt: (projectId: string, halted: boolean, reason = '') =>
    apiPut<CatalogueState>(`/v1/ai-agents/catalogue/projects/${encodeURIComponent(projectId)}/halt`, { halted, reason }),
  run: (projectId: string, agent: CatalogueAgentName, inputs: Record<string, string>) =>
    apiPost<{ run: CatalogueRun; draft: AgentDraft | null }>(`/v1/ai-agents/catalogue/projects/${encodeURIComponent(projectId)}/agents/${agent}/run`, { inputs }),
  drafts: (projectId: string) =>
    apiGet<{ items: AgentDraft[]; total: number }>(`/v1/ai-agents/catalogue/projects/${encodeURIComponent(projectId)}/drafts?limit=500`).then((r) => r.items),
  review: (
    projectId: string,
    draftId: string,
    body: { decision: 'accepted' | 'rejected'; note?: string; apply?: boolean },
  ) => apiPost<AgentDraft>(`/v1/ai-agents/catalogue/projects/${encodeURIComponent(projectId)}/drafts/${draftId}/review`, body),
  runs: (projectId: string) =>
    apiGet<{ items: CatalogueRun[]; total: number }>(`/v1/ai-agents/catalogue/projects/${encodeURIComponent(projectId)}/runs?limit=50`).then((r) => r.items),
  validation: (projectId: string, locale: string) =>
    apiGet<{ checked: number; findings: DraftFinding[] }>(
      `/v1/ai-agents/catalogue/projects/${encodeURIComponent(projectId)}/validation?locale=${encodeURIComponent(locale)}`,
    ),
};

/** Catalogue link that preselects an agent and prefills its inputs (used by the "Run agent" entry points). */
export function catalogueRunLink(agent: CatalogueAgentName, inputs: Record<string, string> = {}): string {
  const params = new URLSearchParams({ agent, ...inputs });
  return `/ai-agents/catalogue?${params.toString()}`;
}
