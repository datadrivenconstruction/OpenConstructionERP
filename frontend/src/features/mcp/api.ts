// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wire types and calls for the MCP settings surface (`/v1/mcp/...`).
 *
 * The MCP endpoint itself (`POST /api/v1/mcp`) is for external AI clients and
 * is never called from the browser; this file only manages the person's switch,
 * tokens, call log and validation findings.
 */
import type { Page } from '@/shared/lib/apiHelpers';
import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/lib/api';

export const MCP_BASE = '/v1/mcp';
/** Path an external client posts to, relative to the server origin. */
export const MCP_ENDPOINT_PATH = '/api/v1/mcp';

export interface McpSettings {
  enabled: boolean;
  rate_limit_per_minute: number;
  endpoint_path: string;
  protocol_versions: string[];
}

export interface McpToken {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  can_propose: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface McpTokenCreated extends McpToken {
  /** The secret; returned once, never again. */
  token: string;
}

export type McpToolKind = 'read' | 'propose';
export type McpCallOutcome = 'ok' | 'error' | 'denied' | 'rate_limited';

export interface McpToolInfo {
  name: string;
  kind: McpToolKind;
  description: string;
  permission: string | null;
  available: boolean;
}

export interface McpToolCall {
  id: string;
  tool: string;
  kind: McpToolKind | null;
  outcome: McpCallOutcome;
  duration_ms: number | null;
  project_id: string | null;
  token_prefix: string | null;
  action_id: string | null;
  error: string | null;
  created_at: string;
}

export interface McpValidationFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  key: string;
  message: string;
  params: Record<string, unknown>;
  element_ref: string | null;
}

export interface McpValidationReport {
  status: string;
  score: number | null;
  findings: McpValidationFinding[];
}

export interface McpTokenCreate {
  name: string;
  expires_in_days: number | null;
  can_propose: boolean;
}

export const mcpKeys = {
  all: ['mcp'] as const,
  settings: ['mcp', 'settings'] as const,
  tokens: ['mcp', 'tokens'] as const,
  calls: ['mcp', 'calls'] as const,
  tools: ['mcp', 'tools'] as const,
  validation: ['mcp', 'validation'] as const,
  pending: ['mcp', 'pending-proposals'] as const,
};

export const getMcpSettings = () => apiGet<McpSettings>(`${MCP_BASE}/settings/`);
export const updateMcpSettings = (body: Partial<Pick<McpSettings, 'enabled' | 'rate_limit_per_minute'>>) =>
  apiPut<McpSettings>(`${MCP_BASE}/settings/`, body);
export const listMcpTokens = () => apiGet<Page<McpToken>>(`${MCP_BASE}/tokens/`).then((page) => page.items);
export const createMcpToken = (body: McpTokenCreate) => apiPost<McpTokenCreated>(`${MCP_BASE}/tokens/`, body);
export const revokeMcpToken = (id: string) => apiDelete(`${MCP_BASE}/tokens/${encodeURIComponent(id)}/`);
export const listMcpCalls = (limit = 25) =>
  apiGet<Page<McpToolCall>>(`${MCP_BASE}/calls/?limit=${limit}`).then((page) => page.items);
export const listMcpTools = () => apiGet<McpToolInfo[]>(`${MCP_BASE}/tools/`);
export const getMcpValidation = () => apiGet<McpValidationReport>(`${MCP_BASE}/validation/`);
