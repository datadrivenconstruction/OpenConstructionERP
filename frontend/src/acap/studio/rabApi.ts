import { apiPost, triggerDownload } from '@/shared/lib/api';

const PREFIX = '/v1/acap';

export interface RabLine {
  kode: string;
  uraian: string;
  unit: string;
  quantity: string | number;
  unit_rate: string | number | null;
  total: string | number | null;
  price_missing: boolean;
  kategori: string;
  missing_resources: unknown[];
  curated_resources: unknown[];
}

export interface RabResponse {
  boq_id: string;
  grand_total: string;
  subtotals_by_kategori: Record<string, string>;
  lines: RabLine[];
  price_missing_lines: RabLine[];
  curated_lines: RabLine[];
  not_covered: string[];
}

export function generateRab(projectId: string): Promise<RabResponse> {
  return apiPost<RabResponse>(`${PREFIX}/projects/${projectId}/rab:generate`, {}, { longRunning: true });
}

export async function downloadRabCsv(projectId: string, csvContent: string): Promise<void> {
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  triggerDownload(blob, `rab-${projectId}.csv`);
}
