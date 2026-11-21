// Design module (ERP side of the design editor link).
/** Model panel: the values `ddc gen` takes, with the generator's ranges, and "generate a revision from them". */
import { apiGet, apiPost } from '@/shared/lib/api';

export type ModelValue = number | boolean | string | null;

export interface ModelParam {
  id: string;
  pointer: string;
  kind: 'int' | 'number' | 'bool' | 'choice';
  unit: string | null;
  min: number | null;
  max: number | null;
  step: number | null;
  options: (string | null)[] | null;
  nullable: boolean;
  value: ModelValue;
  /** What the generator uses when the brief leaves the value out; null: the builder sizes it. */
  default: ModelValue;
  /** generator.spec_overrides in the brief sets this: not editable here. */
  overridden: boolean;
}

export interface ModelUnit {
  index: number;
  pointer: string;
  name: string | null;
  value: number;
  min: number;
  max: number;
  per_floor: number;
  overridden: boolean;
}

export interface ModelPreset {
  id: 'floor_up' | 'floor_down' | 'site_limit' | string;
  values: Record<string, ModelValue>;
}

export interface ModelView {
  typology: string | null;
  brief_version: number;
  params: ModelParam[];
  units: ModelUnit[];
  max_units_per_floor: number | null;
  /** facade one flat needs, m: with the width, flats per floor = 2 x floor(width / frontage), up to apartments_top */
  apartment_frontage?: number | null;
  apartments_top?: number;
  presets: ModelPreset[];
  reason: string | null;
  source: string;
}

export function fetchModel(projectId: string): Promise<ModelView> {
  return apiGet<ModelView>(`/v1/design/projects/${projectId}/model`);
}

export interface ModelStart {
  job_id: string;
  brief_version: number;
  changed: string[];
}

export function generateModel(projectId: string, briefVersion: number, values: Record<string, ModelValue>): Promise<ModelStart> {
  return apiPost<ModelStart, { brief_version: number; values: Record<string, ModelValue> }>(
    `/v1/design/projects/${projectId}/model/generate`, { brief_version: briefVersion, values },
  );
}

/** Dry run of generate: the brief `ddc gen --brief` would get for these values (server model_params.apply). */
export interface PreviewAnswer { brief_version: number; brief: unknown; problems?: { message: string; unconfirmed?: string[] } }

/** `brief` is null while the brief is not confirmed; `problems` says why. */
export function previewBrief(projectId: string, briefVersion: number, values: Record<string, ModelValue>): Promise<PreviewAnswer> {
  return apiPost<PreviewAnswer, { brief_version: number; values: Record<string, ModelValue> }>(
    `/v1/design/projects/${projectId}/model/preview`, { brief_version: briefVersion, values },
  );
}

/** Units on one floor as the generator places them: the brief counts the building, the spec one floor. */
export function perFloor(count: number, floors: number): number {
  return Math.max(1, Math.ceil(count / Math.max(1, floors)));
}

/** Problem of one value against the generator's range, or null. */
export function rangeProblem(p: { kind: string; min: number | null; max: number | null; nullable: boolean; options?: (string | null)[] | null }, v: ModelValue): 'required' | 'range' | 'integer' | null {
  if (v === null || v === '') return p.nullable ? null : 'required';
  if (p.kind === 'int' || p.kind === 'number') {
    if (typeof v !== 'number' || !Number.isFinite(v)) return 'range';
    if (p.kind === 'int' && !Number.isInteger(v)) return 'integer';
    if ((p.min !== null && v < p.min) || (p.max !== null && v > p.max)) return 'range';
  }
  return null;
}
