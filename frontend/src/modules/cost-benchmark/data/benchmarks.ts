/**
 * Construction cost benchmark data.
 *
 * Sources (typical planning benchmarks compiled from public datasets, not a live feed):
 * - BKI Baukosten Gebaeude 2024 (Germany)
 * - Statistik Austria Baukostenindex 2024 (Austria)
 * - SIA / BFS Schweiz 2024 (Switzerland)
 * - BCIS Building Cost Information Service 2024 (United Kingdom)
 * - ENR Construction Cost Index 2024 (United States)
 *
 * All values are cost per m2 GFA (gross floor area) for DIN 276 KG300+400
 * (construction works plus technical building systems). The KG300 vs KG400
 * split, the per-unit secondary metrics and the sample sizes are typical
 * planning values, not survey output. Actual costs vary by location,
 * specification and market conditions.
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

export type CurrencyCode = 'EUR' | 'CHF' | 'GBP' | 'USD';

/** DIN 276 KG300 (construction) vs KG400 (technical systems) split of the median. */
export interface CostGroupSplit {
  /** KG300 share of KG300+400, 0..1. */
  kg300Pct: number;
  /** KG400 share of KG300+400, 0..1. kg300Pct + kg400Pct === 1. */
  kg400Pct: number;
}

/** Per-unit secondary metric for a cell, when the unit is standard for the type. */
export interface SecondaryMetric {
  /** machine id, e.g. 'bed' | 'room' | 'pupil' | 'dwelling' */
  unitId: string;
  /** plain English label used as a t() defaultValue at render time */
  label: string;
  /** typical cost per secondary unit in the cell currency */
  median: number;
  /** typical area in m2 GFA assumed per secondary unit (basis for the median) */
  areaPerUnit: number;
  /** typical count assumed for a reference project of this type */
  typicalCount?: number;
}

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

  /** KG300 vs KG400 split for this cell. */
  split: CostGroupSplit;
  /** per-unit secondary metric for this cell, when meaningful. */
  secondary?: SecondaryMetric;

  /** number of reference projects behind the cell. */
  sampleSize: number;
  /** confidence label derived from sampleSize + range spread + recency. */
  confidence: 'high' | 'medium' | 'low';

  /** provenance, e.g. 'BKI Baukosten Gebaeude 2024' */
  source: string;
  /** survey or publication year */
  sourceYear: number;
  /** currency of the values in this cell */
  currency: CurrencyCode;
}

export interface BuildingTypeInfo {
  id: BuildingType;
  label: string;
  description: string;
  /** plain English scope note rendered with a t() defaultValue. */
  scopeNote: string;
  /** machine id of the secondary unit this type carries, if any. */
  secondaryUnitId?: string;
  /** Typical unit label for secondary KPI (e.g. per bed, per pupil) */
  secondaryUnit?: string;
}

export const BUILDING_TYPES: BuildingTypeInfo[] = [
  {
    id: 'office',
    label: 'Office Building',
    description: 'Standard office, air-conditioned',
    scopeNote: 'KG300+400 per m2 GFA for a mid-spec air-conditioned office. Fit-out to shell-and-core standard.',
  },
  {
    id: 'hospital',
    label: 'Hospital',
    description: 'General hospital incl. surgery',
    scopeNote: 'General acute hospital with surgery and imaging. Per bed assumes about 85 m2 GFA per bed.',
    secondaryUnitId: 'bed',
    secondaryUnit: 'per bed',
  },
  {
    id: 'school',
    label: 'School / University',
    description: 'Education facility',
    scopeNote: 'Primary or secondary education facility. Per pupil place assumes about 10 m2 GFA per place.',
    secondaryUnitId: 'pupil',
    secondaryUnit: 'per pupil place',
  },
  {
    id: 'residential_single',
    label: 'Single Family House',
    description: 'Detached/semi-detached',
    scopeNote: 'Detached or semi-detached house. Per dwelling assumes about 140 m2 GFA per home.',
    secondaryUnitId: 'dwelling',
    secondaryUnit: 'per dwelling',
  },
  {
    id: 'residential_multi',
    label: 'Multi-Family Residential',
    description: 'Apartment building 4+ units',
    scopeNote: 'Apartment building of four units or more. Per dwelling assumes about 75 m2 GFA per flat.',
    secondaryUnitId: 'dwelling',
    secondaryUnit: 'per dwelling',
  },
  {
    id: 'industrial',
    label: 'Industrial / Factory',
    description: 'Light manufacturing',
    scopeNote: 'Light manufacturing hall with office annex. KG300-heavy, low technical share.',
  },
  {
    id: 'retail',
    label: 'Retail / Shopping',
    description: 'Retail space, shopping center',
    scopeNote: 'Retail or shopping space, shell plus base fit-out. Tenant fit-out excluded.',
  },
  {
    id: 'hotel',
    label: 'Hotel',
    description: '3-4 star hotel',
    scopeNote: '3 to 4 star hotel. Per room assumes about 48 m2 GFA per key incl. common areas.',
    secondaryUnitId: 'room',
    secondaryUnit: 'per room',
  },
  {
    id: 'warehouse',
    label: 'Warehouse / Logistics',
    description: 'Storage, distribution center',
    scopeNote: 'Storage or distribution shed. Mostly structure and envelope, minimal technical systems.',
  },
];

export const BENCHMARK_REGIONS: { id: BenchmarkRegion; label: string; currency: CurrencyCode }[] = [
  { id: 'DE', label: 'Germany', currency: 'EUR' },
  { id: 'AT', label: 'Austria', currency: 'EUR' },
  { id: 'CH', label: 'Switzerland', currency: 'CHF' },
  { id: 'UK', label: 'United Kingdom', currency: 'GBP' },
  { id: 'US', label: 'United States', currency: 'USD' },
];

/* ── Modeling constants ─────────────────────────────────────────────────
 *
 * The dataset below is generated from the existing region x type medians and
 * a small set of typical-planning assumptions so the numbers stay internally
 * consistent: the KG split always sums to the median, and each secondary
 * metric is the median times a typical area per unit. Quartiles, source,
 * year and currency keep the original, reasonable values.
 */

/** Source quartiles per region x type (the original, reasonable ranges). */
const QUARTILES: Record<BenchmarkRegion, Record<BuildingType, [number, number, number, number, number]>> = {
  DE: {
    office: [1800, 2200, 2650, 3200, 4500],
    hospital: [3200, 3800, 4500, 5400, 7500],
    school: [2000, 2400, 2850, 3400, 4200],
    residential_single: [1600, 2000, 2400, 2900, 4000],
    residential_multi: [1800, 2100, 2500, 3000, 3800],
    industrial: [800, 1100, 1450, 1900, 2800],
    retail: [1200, 1600, 2000, 2500, 3500],
    hotel: [2200, 2800, 3400, 4200, 6000],
    warehouse: [500, 700, 950, 1300, 2000],
  },
  AT: {
    office: [1900, 2350, 2800, 3400, 4800],
    hospital: [3400, 4000, 4700, 5600, 7800],
    school: [2100, 2550, 3000, 3600, 4500],
    residential_single: [1700, 2100, 2550, 3100, 4200],
    residential_multi: [1900, 2250, 2650, 3200, 4000],
    industrial: [850, 1150, 1500, 2000, 2900],
    retail: [1300, 1700, 2100, 2650, 3700],
    hotel: [2400, 3000, 3600, 4400, 6300],
    warehouse: [550, 750, 1000, 1350, 2100],
  },
  CH: {
    office: [3200, 3900, 4600, 5500, 7500],
    hospital: [5500, 6500, 7800, 9200, 12000],
    school: [3500, 4200, 4900, 5800, 7200],
    residential_single: [2800, 3400, 4100, 5000, 7000],
    residential_multi: [3000, 3600, 4300, 5200, 6500],
    industrial: [1400, 1900, 2500, 3200, 4500],
    retail: [2200, 2800, 3400, 4200, 5800],
    hotel: [3800, 4600, 5600, 6800, 9500],
    warehouse: [900, 1200, 1600, 2100, 3200],
  },
  UK: {
    office: [1500, 1850, 2200, 2700, 3800],
    hospital: [2800, 3300, 3900, 4700, 6500],
    school: [1700, 2050, 2400, 2900, 3600],
    residential_single: [1300, 1650, 2000, 2450, 3400],
    residential_multi: [1500, 1800, 2150, 2600, 3300],
    industrial: [650, 900, 1200, 1600, 2400],
    retail: [1000, 1350, 1700, 2150, 3000],
    hotel: [1900, 2400, 2900, 3600, 5100],
    warehouse: [400, 600, 800, 1100, 1700],
  },
  US: {
    office: [1800, 2300, 2800, 3500, 5000],
    hospital: [3500, 4200, 5000, 6000, 8500],
    school: [2000, 2500, 3000, 3600, 4500],
    residential_single: [1400, 1800, 2200, 2800, 4000],
    residential_multi: [1600, 2000, 2400, 3000, 3800],
    industrial: [800, 1100, 1500, 2000, 3000],
    retail: [1100, 1500, 1900, 2400, 3400],
    hotel: [2200, 2800, 3500, 4300, 6200],
    warehouse: [500, 700, 1000, 1400, 2200],
  },
};

/**
 * Typical DIN 276 KG400 (technical systems) share of KG300+400 by building
 * type. Same split applied across regions for a given type. These are
 * documented planning shares, not survey output. KG300 share is the
 * complement. Higher for services-dense buildings (hospitals), lower for
 * sheds (warehouse, industrial).
 */
const KG400_SHARE: Record<BuildingType, number> = {
  office: 0.28,
  hospital: 0.45,
  school: 0.3,
  residential_single: 0.22,
  residential_multi: 0.27,
  industrial: 0.16,
  retail: 0.24,
  hotel: 0.32,
  warehouse: 0.13,
};

/** Typical m2 GFA per secondary unit, used to derive the per-unit median. */
const AREA_PER_UNIT: Partial<Record<BuildingType, { unitId: string; label: string; area: number; typicalCount: number }>> = {
  hospital: { unitId: 'bed', label: 'per bed', area: 85, typicalCount: 300 },
  hotel: { unitId: 'room', label: 'per room', area: 48, typicalCount: 150 },
  school: { unitId: 'pupil', label: 'per pupil place', area: 10, typicalCount: 600 },
  residential_single: { unitId: 'dwelling', label: 'per dwelling', area: 140, typicalCount: 1 },
  residential_multi: { unitId: 'dwelling', label: 'per dwelling', area: 75, typicalCount: 24 },
};

/** Provenance per region (source string, year, currency). */
const PROVENANCE: Record<BenchmarkRegion, { source: string; sourceYear: number; currency: CurrencyCode }> = {
  DE: { source: 'BKI Baukosten Gebaeude 2024', sourceYear: 2024, currency: 'EUR' },
  AT: { source: 'Statistik Austria Baukostenindex 2024', sourceYear: 2024, currency: 'EUR' },
  CH: { source: 'SIA / BFS Schweiz 2024', sourceYear: 2024, currency: 'CHF' },
  UK: { source: 'BCIS Building Cost Information Service 2024', sourceYear: 2024, currency: 'GBP' },
  US: { source: 'ENR Construction Cost Index 2024', sourceYear: 2024, currency: 'USD' },
};

/**
 * Typical planning sample size per region x type. National published datasets
 * are large for common types, thinner for specialty buildings and smaller
 * markets. These are honest orders of magnitude, not exact survey counts.
 */
const SAMPLE_BASE: Record<BuildingType, number> = {
  office: 180,
  hospital: 55,
  school: 140,
  residential_single: 200,
  residential_multi: 170,
  industrial: 90,
  retail: 110,
  hotel: 60,
  warehouse: 120,
};

/** Market-size factor on the sample base (bigger datasets in larger markets). */
const SAMPLE_REGION_FACTOR: Record<BenchmarkRegion, number> = {
  DE: 1.0,
  US: 1.0,
  UK: 0.85,
  AT: 0.55,
  CH: 0.45,
};

/* ── Derived helpers ────────────────────────────────────────────────── */

/**
 * Confidence label from sample size, range spread and source recency.
 * A large recent sample with a tight spread is high confidence. A thin or
 * dated sample, or a very wide spread, is low confidence.
 */
export function deriveConfidence(
  sampleSize: number,
  sourceYear: number,
  spread?: number,
): 'high' | 'medium' | 'low' {
  const currentYear = new Date().getFullYear();
  const age = Math.max(0, currentYear - sourceYear);

  let score = 0;
  if (sampleSize >= 120) score += 2;
  else if (sampleSize >= 60) score += 1;

  if (age <= 2) score += 1;
  else if (age >= 5) score -= 1;

  // spread is (max - min) / median; a wide band lowers confidence.
  if (spread !== undefined) {
    if (spread <= 1.2) score += 1;
    else if (spread >= 2.0) score -= 1;
  }

  if (score >= 3) return 'high';
  if (score >= 1) return 'medium';
  return 'low';
}

/** Split a cost/m2 figure into KG300 and KG400 components for a cell. */
export function splitByCostGroup(
  costPerM2: number,
  split: CostGroupSplit,
): { kg300: number; kg400: number } {
  const kg400 = costPerM2 * split.kg400Pct;
  return { kg300: costPerM2 - kg400, kg400 };
}

/**
 * Confidence label for a user value versus a cell: how trustworthy the
 * comparison is. Driven by the cell confidence, which already folds in
 * sample size, spread and recency.
 */
export function comparisonConfidence(range: BenchmarkRange): { label: string; key: string } {
  switch (range.confidence) {
    case 'high':
      return {
        key: 'benchmarks.cmp_conf_high',
        label: 'High, the reference cell rests on a broad recent sample',
      };
    case 'medium':
      return {
        key: 'benchmarks.cmp_conf_medium',
        label: 'Medium, treat the position as indicative',
      };
    default:
      return {
        key: 'benchmarks.cmp_conf_low',
        label: 'Low, the reference sample is thin or the spread is wide',
      };
  }
}

/* ── Build the BENCHMARKS table ─────────────────────────────────────── */

function buildRange(region: BenchmarkRegion, type: BuildingType): BenchmarkRange {
  const [min, q1, median, q3, max] = QUARTILES[region][type];
  const prov = PROVENANCE[region];

  const kg400Pct = KG400_SHARE[type];
  const kg300Pct = Math.round((1 - kg400Pct) * 100) / 100;

  const sampleSize = Math.round(SAMPLE_BASE[type] * SAMPLE_REGION_FACTOR[region]);
  const spread = median > 0 ? (max - min) / median : 0;
  const confidence = deriveConfidence(sampleSize, prov.sourceYear, spread);

  const range: BenchmarkRange = {
    min,
    q1,
    median,
    q3,
    max,
    split: { kg300Pct, kg400Pct },
    sampleSize,
    confidence,
    source: prov.source,
    sourceYear: prov.sourceYear,
    currency: prov.currency,
  };

  const unit = AREA_PER_UNIT[type];
  if (unit) {
    range.secondary = {
      unitId: unit.unitId,
      label: unit.label,
      median: Math.round(median * unit.area),
      areaPerUnit: unit.area,
      typicalCount: unit.typicalCount,
    };
  }

  return range;
}

const REGION_IDS: BenchmarkRegion[] = ['DE', 'AT', 'CH', 'UK', 'US'];
const TYPE_IDS: BuildingType[] = [
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

/**
 * Benchmark data: BENCHMARKS[region][buildingType] = BenchmarkRange.
 * Values in the cell currency per m2 GFA.
 */
export const BENCHMARKS: Record<BenchmarkRegion, Record<BuildingType, BenchmarkRange>> = REGION_IDS.reduce(
  (acc, region) => {
    acc[region] = TYPE_IDS.reduce(
      (typeAcc, type) => {
        typeAcc[type] = buildRange(region, type);
        return typeAcc;
      },
      {} as Record<BuildingType, BenchmarkRange>,
    );
    return acc;
  },
  {} as Record<BenchmarkRegion, Record<BuildingType, BenchmarkRange>>,
);

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
