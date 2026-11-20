// Design module (ERP side of the design editor link).
/** The ERP's own suggestions for a position without a direct cost item: Cost Match and assemblies. A person confirms. */
import { apiPost } from '@/shared/lib/api';

const P = (projectId: string, positionId: string) => `/v1/design/projects/${projectId}/estimate/positions/${positionId}`;

export interface CostMatchCandidate {
  cost_item_id: string; code: string; description: string; unit: string; rate: string | null; currency: string;
  confidence: string; suggested: boolean; usable: boolean; unusable_reason: 'unit' | 'currency' | 'rate' | null;
}
export interface AssemblyCandidate {
  assembly_id: string; code: string; name: string; unit: string; rate: string; currency: string;
  shared_words: string[]; usable: boolean; unusable_reason: 'unit' | 'currency' | 'rate' | null;
}
export interface Suggestions {
  position_id: string; unit: string; currency: string; assemblies: AssemblyCandidate[];
  cost_match: null | { run_id: string; result_id: string; region: string; tier: string; tie: boolean; hint: string; candidates: CostMatchCandidate[] };
}

export const fetchSuggestions = (projectId: string, positionId: string) =>
  apiPost<Suggestions>(`${P(projectId, positionId)}/suggestions`, {});

export type Confirmation = { result_id: string; cost_item_id: string } | { assembly_id: string };
export const confirmSuggestion = (projectId: string, positionId: string, body: Confirmation) =>
  apiPost<void, Confirmation>(`${P(projectId, positionId)}/confirm-suggestion`, body);
