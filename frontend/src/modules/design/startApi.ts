// Design module (ERP side of the design editor link).
/** Project start: templates, drawings and photos read by the R5 extraction. Nothing here writes the brief. */
import { apiGet, apiPost } from '@/shared/lib/api';
import { uploadDocument } from '@/features/documents/api';
import { LINK_VERSION, type Extraction } from './api';
import type { BriefDoc } from './data/briefModel';

const HEADERS = { 'X-DDC-Link': LINK_VERSION };

export interface TemplateValue { pointer: string; value: string | number | boolean; doubtful: boolean }
export interface StartTemplate { id: string; typology: string; max_floors: number; values: TemplateValue[]; source: string }

export const fetchTemplates = () =>
  apiGet<{ templates: StartTemplate[]; source: string }>('/v1/design/templates', { headers: HEADERS });

/** File types the extraction reads (brief_sources.py): PDF text or pages, DWG/DXF annotations, images. */
export const ACCEPT = ['.pdf', '.dwg', '.dxf', '.png', '.jpg', '.jpeg', '.webp'];
export const MAX_FILES = 20;

export function acceptable(name: string): boolean {
  const i = name.lastIndexOf('.');
  return i > 0 && ACCEPT.includes(name.slice(i).toLowerCase());
}

/** Drawings go to Documents as drawings, photos as other files: they stay in the project and can be cited later. */
export function uploadSource(projectId: string, file: File) {
  const image = /\.(png|jpe?g|webp)$/i.test(file.name);
  return uploadDocument(projectId, file, image ? 'other' : 'drawing');
}

export function extractFromFiles(projectId: string, documentIds: string[], current: BriefDoc | null, text = ''): Promise<Extraction> {
  return apiPost<Extraction, { document_ids: string[]; text: string | null; use_ai: boolean; base: BriefDoc | null }>(
    `/v1/design/projects/${projectId}/brief/extract`,
    { document_ids: documentIds, text: text.trim() || null, use_ai: true, base: current },
    { headers: HEADERS },
  );
}
