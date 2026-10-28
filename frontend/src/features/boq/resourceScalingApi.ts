// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client for proportional scaling of resource norms (hours, cost or quantity
 * of a section, a set of positions or one resource group) to a target total.
 *
 * Shapes mirror ``backend/app/modules/boq/resource_scaling.py``. Numbers are
 * decimal strings on the wire.
 */
import { ApiError, apiPost } from '@/shared/lib/api';

export type ScaleMetric = 'hours' | 'cost' | 'quantity';
export type RoundingMode = 'half_up' | 'up' | 'down';

export interface ScaleScopeInput {
  sectionId?: string | null;
  positionIds?: string[] | null;
  resourceType?: string | null;
  resourceKey?: string | null;
}

export interface ScaleRequestInput extends ScaleScopeInput {
  metric: ScaleMetric;
  target: string | null;
  decimals: number;
  roundingMode: RoundingMode;
  excludedPositionIds: string[];
  expectedFactor?: string | null;
}

export interface ScaleChange {
  index: number;
  name: string;
  type: string;
  unit: string;
  old_quantity: string;
  new_quantity: string;
}

export interface ScalePlanLine {
  id: string;
  ordinal: string;
  description: string;
  status: 'scaled' | 'locked' | 'excluded' | 'unchanged';
  old_value: string;
  new_value: string;
  changes: ScaleChange[];
}

export interface ScalePlan {
  metric: ScaleMetric;
  target: string;
  current: string;
  fixed: string;
  scalable: string;
  factor: string;
  achieved: string;
  drift: string;
  rounding: { decimals: number; mode: RoundingMode };
  units: string[];
  warnings: { code: string; count?: number; units?: string[] }[];
  counts: { scaled: number; locked: number; excluded: number; no_match: number };
  lines: ScalePlanLine[];
}

export interface ScaleApplyResult {
  plan: ScalePlan;
  snapshot_id: string | null;
  updated: number;
}

function body(input: ScaleRequestInput): Record<string, unknown> {
  return {
    metric: input.metric,
    target: input.target,
    section_id: input.sectionId ?? null,
    position_ids: input.positionIds ?? null,
    resource_type: input.resourceType ?? null,
    resource_key: input.resourceKey ?? null,
    decimals: input.decimals,
    rounding_mode: input.roundingMode,
    excluded_position_ids: input.excludedPositionIds,
    expected_factor: input.expectedFactor ?? null,
  };
}

export function previewScaling(boqId: string, input: ScaleRequestInput): Promise<ScalePlan> {
  return apiPost<ScalePlan>(`/v1/boq/boqs/${encodeURIComponent(boqId)}/resources/scale/preview/`, body(input));
}

export function applyScaling(boqId: string, input: ScaleRequestInput): Promise<ScaleApplyResult> {
  return apiPost<ScaleApplyResult>(`/v1/boq/boqs/${encodeURIComponent(boqId)}/resources/scale/apply/`, body(input));
}

/** The ``code`` of a refused scaling request, or null for any other failure. */
export function scalingErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const detail = (err.body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === 'object' && 'code' in detail && typeof (detail as { code: unknown }).code === 'string') {
    return (detail as { code: string }).code;
  }
  return null;
}
