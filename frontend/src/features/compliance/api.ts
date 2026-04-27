// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Compliance NL Rule Builder API client.
//
// Wraps the T13 NL → DSL builder endpoint plus the existing T08
// compile/save endpoint so the React feature has a single import.

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Types ──────────────────────────────────────────────────────────────── */

export interface NlBuildRequest {
  text: string;
  lang: string;
  use_ai?: boolean;
}

export interface NlBuildResult {
  dsl_definition: Record<string, unknown>;
  dsl_yaml: string | null;
  confidence: number;
  used_method: 'pattern' | 'ai' | 'fallback';
  matched_pattern: string | null;
  errors: string[];
  suggestions: string[];
}

export interface NlPattern {
  pattern_id: string;
  name_key: string;
  confidence: number;
}

export interface NlPatternsResponse {
  items: NlPattern[];
}

export interface DSLCompileResult {
  id: string;
  rule_id: string;
  name: string;
  severity: string;
  standard: string;
  description: string | null;
  definition_yaml: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/* ── Endpoints ──────────────────────────────────────────────────────────── */

/** Convert plain text to a DSL definition using the deterministic
 *  pattern matcher (with optional AI fallback). */
export async function parseNlToDsl(
  body: NlBuildRequest,
): Promise<NlBuildResult> {
  return apiPost<NlBuildResult>('/v1/compliance/dsl/from-nl', body);
}

/** List the supported NL → DSL patterns for the hints panel. */
export async function listNlPatterns(): Promise<NlPattern[]> {
  const res = await apiGet<NlPatternsResponse>(
    '/v1/compliance/dsl/nl-patterns',
  );
  return res.items;
}

/** Compile + persist a DSL rule (re-uses the T08 endpoint). */
export async function saveDslRule(
  definition_yaml: string,
  activate: boolean = true,
): Promise<DSLCompileResult> {
  return apiPost<DSLCompileResult>('/v1/compliance/dsl/compile', {
    definition_yaml,
    activate,
  });
}
