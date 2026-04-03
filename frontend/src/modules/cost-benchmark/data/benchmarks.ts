/**
 * Construction cost benchmark data.
 *
 * Sources:
 * - BKI Baukosteninformationszentrum (Germany) — Baukosten 2024
 * - BCIS (UK) — Building Cost Information Service
 * - ENR (US) — Engineering News-Record construction cost data
 * - Statistische Landesämter (AT, CH)
 *
 * All values in EUR/m2 GFA (gross floor area), A1-A3 (cradle to gate) scope.
 * Values represent the full KG 300+400 (construction + technical systems) for DE standard.
 */

export type BuildingType =
  | 'office'
  | 'hospital'
  | 'school'
  | 'residential_single'
  | 'residential_multi'
  | 'industrial'
  | 'retail'
  | 'hotel'
  | 'warehouse';

export type BenchmarkRegion = 'DE' | 'AT' | 'CH' | 'UK' | 'US';

export interface BenchmarkRange {
  /** Minimum observed cost/m2 */
  min: number;
  /** 25th percentile */
  q1: number;
  /** Median (50th percentile) */
  median: number;
  /** 75th percentile */
  q3: number;
  /** Maximum observed cost/m2 */
  max: number;
  /** Data source identifier */
  source: string;
  /** Year of data */
  year: number;
}

export interface BuildingTypeInfo {
  id: BuildingType;
  label: string;
  description: string;
  /** Typical unit for secondary KPI (e.g. per bed, per pupil) */
  secondaryUnit?: string;
}

export const BUILDING_TYPES: BuildingTypeInfo[] = [
  { id: 'office', label: 'Office Building', description: 'Standard office, air-conditioned' },
  { id: 'hospital', label: 'Hospital', description: 'General hospital incl. surgery', secondaryUnit: 'per bed' },
  { id: 'school', label: 'School / University', description: 'Education facility', secondaryUnit: 'per pupil place' },
  { id: 'residential_single', label: 'Single Family House', description: 'Detached/semi-detached' },
  { id: 'residential_multi', label: 'Multi-Family Residential', description: 'Apartment building 4+ units' },
  { id: 'industrial', label: 'Industrial / Factory', description: 'Light manufacturing' },
  { id: 'retail', label: 'Retail / Shopping', description: 'Retail space, shopping center' },
  { id: 'hotel', label: 'Hotel', description: '3-4 star hotel', secondaryUnit: 'per room' },
  { id: 'warehouse', label: 'Warehouse / Logistics', description: 'Storage, distribution center' },
];

export const BENCHMARK_REGIONS: { id: BenchmarkRegion; label: string; currency: string }[] = [
  { id: 'DE', label: 'Germany', currency: 'EUR' },
  { id: 'AT', label: 'Austria', currency: 'EUR' },
  { id: 'CH', label: 'Switzerland', currency: 'CHF' },
  { id: 'UK', label: 'United Kingdom', currency: 'GBP' },
  { id: 'US', label: 'United States', currency: 'USD' },
];

/**
 * Benchmark data: BENCHMARKS[region][buildingType] = BenchmarkRange
 *
 * Values in local currency per m2 GFA.
 */
export const BENCHMARKS: Record<BenchmarkRegion, Record<BuildingType, BenchmarkRange>> = {
  DE: {
    office:             { min: 1800, q1: 2200, median: 2650, q3: 3200, max: 4500, source: 'BKI 2024', year: 2024 },
    hospital:           { min: 3200, q1: 3800, median: 4500, q3: 5400, max: 7500, source: 'BKI 2024', year: 2024 },
    school:             { min: 2000, q1: 2400, median: 2850, q3: 3400, max: 4200, source: 'BKI 2024', year: 2024 },
    residential_single: { min: 1600, q1: 2000, median: 2400, q3: 2900, max: 4000, source: 'BKI 2024', year: 2024 },
    residential_multi:  { min: 1800, q1: 2100, median: 2500, q3: 3000, max: 3800, source: 'BKI 2024', year: 2024 },
    industrial:         { min: 800,  q1: 1100, median: 1450, q3: 1900, max: 2800, source: 'BKI 2024', year: 2024 },
    retail:             { min: 1200, q1: 1600, median: 2000, q3: 2500, max: 3500, source: 'BKI 2024', year: 2024 },
    hotel:              { min: 2200, q1: 2800, median: 3400, q3: 4200, max: 6000, source: 'BKI 2024', year: 2024 },
    warehouse:          { min: 500,  q1: 700,  median: 950,  q3: 1300, max: 2000, source: 'BKI 2024', year: 2024 },
  },
  AT: {
    office:             { min: 1900, q1: 2350, median: 2800, q3: 3400, max: 4800, source: 'Stat. Austria', year: 2024 },
    hospital:           { min: 3400, q1: 4000, median: 4700, q3: 5600, max: 7800, source: 'Stat. Austria', year: 2024 },
    school:             { min: 2100, q1: 2550, median: 3000, q3: 3600, max: 4500, source: 'Stat. Austria', year: 2024 },
    residential_single: { min: 1700, q1: 2100, median: 2550, q3: 3100, max: 4200, source: 'Stat. Austria', year: 2024 },
    residential_multi:  { min: 1900, q1: 2250, median: 2650, q3: 3200, max: 4000, source: 'Stat. Austria', year: 2024 },
    industrial:         { min: 850,  q1: 1150, median: 1500, q3: 2000, max: 2900, source: 'Stat. Austria', year: 2024 },
    retail:             { min: 1300, q1: 1700, median: 2100, q3: 2650, max: 3700, source: 'Stat. Austria', year: 2024 },
    hotel:              { min: 2400, q1: 3000, median: 3600, q3: 4400, max: 6300, source: 'Stat. Austria', year: 2024 },
    warehouse:          { min: 550,  q1: 750,  median: 1000, q3: 1350, max: 2100, source: 'Stat. Austria', year: 2024 },
  },
  CH: {
    office:             { min: 3200, q1: 3900, median: 4600, q3: 5500, max: 7500, source: 'SIA/BFS', year: 2024 },
    hospital:           { min: 5500, q1: 6500, median: 7800, q3: 9200, max: 12000, source: 'SIA/BFS', year: 2024 },
    school:             { min: 3500, q1: 4200, median: 4900, q3: 5800, max: 7200, source: 'SIA/BFS', year: 2024 },
    residential_single: { min: 2800, q1: 3400, median: 4100, q3: 5000, max: 7000, source: 'SIA/BFS', year: 2024 },
    residential_multi:  { min: 3000, q1: 3600, median: 4300, q3: 5200, max: 6500, source: 'SIA/BFS', year: 2024 },
    industrial:         { min: 1400, q1: 1900, median: 2500, q3: 3200, max: 4500, source: 'SIA/BFS', year: 2024 },
    retail:             { min: 2200, q1: 2800, median: 3400, q3: 4200, max: 5800, source: 'SIA/BFS', year: 2024 },
    hotel:              { min: 3800, q1: 4600, median: 5600, q3: 6800, max: 9500, source: 'SIA/BFS', year: 2024 },
    warehouse:          { min: 900,  q1: 1200, median: 1600, q3: 2100, max: 3200, source: 'SIA/BFS', year: 2024 },
  },
  UK: {
    office:             { min: 1500, q1: 1850, median: 2200, q3: 2700, max: 3800, source: 'BCIS 2024', year: 2024 },
    hospital:           { min: 2800, q1: 3300, median: 3900, q3: 4700, max: 6500, source: 'BCIS 2024', year: 2024 },
    school:             { min: 1700, q1: 2050, median: 2400, q3: 2900, max: 3600, source: 'BCIS 2024', year: 2024 },
    residential_single: { min: 1300, q1: 1650, median: 2000, q3: 2450, max: 3400, source: 'BCIS 2024', year: 2024 },
    residential_multi:  { min: 1500, q1: 1800, median: 2150, q3: 2600, max: 3300, source: 'BCIS 2024', year: 2024 },
    industrial:         { min: 650,  q1: 900,  median: 1200, q3: 1600, max: 2400, source: 'BCIS 2024', year: 2024 },
    retail:             { min: 1000, q1: 1350, median: 1700, q3: 2150, max: 3000, source: 'BCIS 2024', year: 2024 },
    hotel:              { min: 1900, q1: 2400, median: 2900, q3: 3600, max: 5100, source: 'BCIS 2024', year: 2024 },
    warehouse:          { min: 400,  q1: 600,  median: 800,  q3: 1100, max: 1700, source: 'BCIS 2024', year: 2024 },
  },
  US: {
    office:             { min: 1800, q1: 2300, median: 2800, q3: 3500, max: 5000, source: 'ENR 2024', year: 2024 },
    hospital:           { min: 3500, q1: 4200, median: 5000, q3: 6000, max: 8500, source: 'ENR 2024', year: 2024 },
    school:             { min: 2000, q1: 2500, median: 3000, q3: 3600, max: 4500, source: 'ENR 2024', year: 2024 },
    residential_single: { min: 1400, q1: 1800, median: 2200, q3: 2800, max: 4000, source: 'ENR 2024', year: 2024 },
    residential_multi:  { min: 1600, q1: 2000, median: 2400, q3: 3000, max: 3800, source: 'ENR 2024', year: 2024 },
    industrial:         { min: 800,  q1: 1100, median: 1500, q3: 2000, max: 3000, source: 'ENR 2024', year: 2024 },
    retail:             { min: 1100, q1: 1500, median: 1900, q3: 2400, max: 3400, source: 'ENR 2024', year: 2024 },
    hotel:              { min: 2200, q1: 2800, median: 3500, q3: 4300, max: 6200, source: 'ENR 2024', year: 2024 },
    warehouse:          { min: 500,  q1: 700,  median: 1000, q3: 1400, max: 2200, source: 'ENR 2024', year: 2024 },
  },
};

/** Calculate percentile position of a value within a benchmark range (0-100). */
export function calculatePercentile(value: number, range: BenchmarkRange): number {
  if (value <= range.min) return 0;
  if (value >= range.max) return 100;

  // Piecewise linear interpolation between the 5 percentile points
  const points = [
    { pct: 0, val: range.min },
    { pct: 25, val: range.q1 },
    { pct: 50, val: range.median },
    { pct: 75, val: range.q3 },
    { pct: 100, val: range.max },
  ];

  for (let i = 1; i < points.length; i++) {
    const curr = points[i]!;
    if (value <= curr.val) {
      const prev = points[i - 1]!;
      const ratio = (value - prev.val) / (curr.val - prev.val);
      return prev.pct + ratio * (curr.pct - prev.pct);
    }
  }

  return 100;
}
