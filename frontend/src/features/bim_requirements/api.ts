// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Typed client for the `bim_requirements` Rules-as-Code endpoints.
 *
 * - `previewYaml` — parse a YAML rule pack (optionally dry-run against
 *   a model) without persisting anything.
 * - `installYaml` — persist a rule pack to a project.
 *
 * Both endpoints accept a JSON body with the raw YAML text. We return the
 * full response so the UI can render parse errors, the parsed pack and
 * the optional dry-run report.
 */

import { apiPost } from '@/shared/lib/api';
import type {
  InstallYamlResponse,
  PreviewYamlResponse,
} from './types';

const PREVIEW_URL = '/v1/bim_requirements/preview-yaml/';
const INSTALL_URL = '/v1/bim_requirements/install-from-yaml/';

export interface PreviewYamlRequest {
  yaml_text: string;
  model_id?: string;
}

export interface InstallYamlRequest {
  yaml_text: string;
  project_id: string;
}

export async function previewYaml(
  body: PreviewYamlRequest,
  init?: RequestInit,
): Promise<PreviewYamlResponse> {
  return apiPost<PreviewYamlResponse, PreviewYamlRequest>(PREVIEW_URL, body, init);
}

export async function installYaml(
  body: InstallYamlRequest,
  init?: RequestInit,
): Promise<InstallYamlResponse> {
  return apiPost<InstallYamlResponse, InstallYamlRequest>(INSTALL_URL, body, init);
}
