/**
 * Auto-fill the Cost Benchmarks inputs from a real project.
 *
 * Given a project id, this hook reads the project's region, building type,
 * gross floor area and currency, and sums its BOQ grand totals into a single
 * total cost. The benchmark page uses the result to pre-fill its four inputs
 * (which stay editable) so the user compares their REAL project against the
 * industry table and their own portfolio, instead of placeholder numbers.
 *
 * Everything degrades gracefully: a project with no BOQs returns a zero
 * total; a project with no recorded area returns `gfa: null` and the page
 * keeps the area input editable.
 */

import { useQuery } from '@tanstack/react-query';
import { projectsApi, type Project } from '@/features/projects/api';
import { boqApi } from '@/features/boq/api';
import type { BuildingType, BenchmarkRegion } from '../data/benchmarks';

export interface ProjectBenchmarkData {
  projectId: string;
  projectName: string;
  region: BenchmarkRegion;
  buildingType: BuildingType;
  /** Total cost summed across the project's BOQ grand totals. */
  totalCost: number;
  /** Gross floor area in m2, or null when not recorded on the project. */
  gfa: number | null;
  currency: string;
}

/** Map a free-form project region / country code to a benchmark region. */
export function mapProjectRegion(
  region: string | null | undefined,
  countryCode?: string | null,
): BenchmarkRegion {
  const r = (region ?? '').trim().toUpperCase();
  const cc = (countryCode ?? '').trim().toUpperCase();

  // Direct two-letter region matches first.
  if (r === 'DE' || r === 'AT' || r === 'CH' || r === 'UK' || r === 'US') {
    return r as BenchmarkRegion;
  }
  // Common free-form region tags.
  if (r === 'GB') return 'UK';
  if (r === 'USA') return 'US';
  if (r === 'DACH') return 'DE';

  // Fall back to the ISO country code.
  const byCountry: Record<string, BenchmarkRegion> = {
    DE: 'DE',
    AT: 'AT',
    CH: 'CH',
    GB: 'UK',
    UK: 'UK',
    US: 'US',
    USA: 'US',
  };
  if (byCountry[cc]) return byCountry[cc];

  // Default to Germany, the richest reference set.
  return 'DE';
}

/** Map a free-form project_type to a benchmark BuildingType. */
export function mapProjectType(projectType: string | null | undefined): BuildingType {
  const t = (projectType ?? '').trim().toLowerCase();
  if (!t) return 'office';

  // Exact ids the benchmark table already uses pass straight through.
  const known: BuildingType[] = [
    'office',
    'hospital',
    'school',
    'residential_single',
    'residential_multi',
    'industrial',
    'retail',
    'hotel',
    'warehouse',
  ];
  if ((known as string[]).includes(t)) return t as BuildingType;

  // Keyword heuristics for human-entered values.
  if (t.includes('hospital') || t.includes('clinic') || t.includes('health')) return 'hospital';
  if (t.includes('school') || t.includes('university') || t.includes('education')) return 'school';
  if (t.includes('hotel') || t.includes('hospitality')) return 'hotel';
  if (t.includes('warehouse') || t.includes('logistic') || t.includes('storage')) return 'warehouse';
  if (t.includes('industr') || t.includes('factory') || t.includes('manufact')) return 'industrial';
  if (t.includes('retail') || t.includes('shop') || t.includes('mall') || t.includes('store')) return 'retail';
  if (t.includes('apartment') || t.includes('multi') || t.includes('flat')) return 'residential_multi';
  if (t.includes('house') || t.includes('single') || t.includes('villa') || t.includes('detached'))
    return 'residential_single';
  if (t.includes('residential') || t.includes('housing')) return 'residential_multi';
  if (t.includes('office') || t.includes('commercial')) return 'office';

  return 'office';
}

/** Read the gross floor area off a project (column first, then metadata). */
function readProjectArea(project: Project): number | null {
  const direct = parseFloat(String(project.gross_floor_area ?? ''));
  if (!isNaN(direct) && direct > 0) return direct;

  const meta = project.metadata as Record<string, unknown> | undefined;
  for (const key of ['gross_floor_area', 'gfa', 'area_m2']) {
    const raw = meta?.[key];
    const val = parseFloat(String(raw ?? ''));
    if (!isNaN(val) && val > 0) return val;
  }
  return null;
}

async function loadProjectBenchmarkData(projectId: string): Promise<ProjectBenchmarkData> {
  const project = await projectsApi.get(projectId);

  // Sum the project's BOQ grand totals. Each BOQ grand_total comes from the
  // full BOQ document; the list endpoint does not carry it, so we fetch each
  // BOQ once. Projects usually have a small number of BOQs.
  let totalCost = 0;
  try {
    const boqs = await boqApi.list(projectId);
    if (boqs.length > 0) {
      const docs = await Promise.all(boqs.map((b) => boqApi.get(b.id).catch(() => null)));
      for (const doc of docs) {
        if (!doc) continue;
        const gt = Number(doc.grand_total);
        if (!isNaN(gt) && gt > 0) totalCost += gt;
      }
    }
  } catch {
    // No BOQ access or no BOQs - leave the total at 0 and let the page
    // keep the cost input editable.
    totalCost = 0;
  }

  return {
    projectId: project.id,
    projectName: project.name,
    region: mapProjectRegion(project.region, project.country_code),
    buildingType: mapProjectType(project.project_type),
    totalCost,
    gfa: readProjectArea(project),
    currency: project.currency || 'EUR',
  };
}

/**
 * React Query hook returning the benchmark inputs derived from a project.
 *
 * Pass `null` to disable the query (manual mode). The query is read-only and
 * cached; selecting a project that was already loaded is instant.
 */
export function useProjectBenchmarkData(projectId: string | null) {
  return useQuery({
    queryKey: ['cost-benchmark', 'project-data', projectId],
    queryFn: () => loadProjectBenchmarkData(projectId as string),
    enabled: !!projectId,
    staleTime: 60_000,
  });
}
