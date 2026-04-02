/**
 * Client-side Monte Carlo simulation engine for cost risk analysis.
 *
 * Supports triangular, uniform, and PERT distributions.
 * Pure functions — no side effects, no DOM, fully testable.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DistributionType = 'triangular' | 'uniform' | 'pert';

export interface RiskParameter {
  /** Position ID from BOQ */
  positionId: string;
  /** Ordinal for display */
  ordinal: string;
  /** Position description */
  description: string;
  /** Base cost (quantity * unit_rate) */
  baseCost: number;
  /** Optimistic multiplier (e.g. 0.85 = 15% less than base) */
  optimistic: number;
  /** Most likely multiplier (typically 1.0) */
  mostLikely: number;
  /** Pessimistic multiplier (e.g. 1.30 = 30% more than base) */
  pessimistic: number;
  /** Distribution type */
  distribution: DistributionType;
}

export interface SimulationResult {
  /** Number of iterations run */
  iterations: number;
  /** Base total (sum of all position baseCosts) */
  baseTotal: number;
  /** Percentile values */
  percentiles: {
    p5: number;
    p10: number;
    p25: number;
    p50: number;
    p75: number;
    p80: number;
    p90: number;
    p95: number;
  };
  /** Mean of all simulation outcomes */
  mean: number;
  /** Standard deviation */
  stdDev: number;
  /** Contingency = P80 - P50 */
  contingency: number;
  /** Contingency as percentage of base total */
  contingencyPct: number;
  /** Histogram bins for visualization */
  histogram: HistogramBin[];
  /** Top risk drivers sorted by variance contribution */
  riskDrivers: RiskDriver[];
}

export interface HistogramBin {
  binStart: number;
  binEnd: number;
  count: number;
  frequency: number;
}

export interface RiskDriver {
  positionId: string;
  ordinal: string;
  description: string;
  baseCost: number;
  varianceContribution: number;
  contributionPct: number;
}

// ---------------------------------------------------------------------------
// Random number generators for distributions
// ---------------------------------------------------------------------------

/** Seeded PRNG (xorshift128+) for reproducible results. */
export function createRNG(seed: number): () => number {
  let s0 = seed | 0 || 1;
  let s1 = (seed * 0x6d2b79f5) | 0 || 2;
  return () => {
    let a = s0;
    const b = s1;
    s0 = b;
    a ^= a << 23;
    a ^= a >>> 17;
    a ^= b;
    a ^= b >>> 26;
    s1 = a;
    return ((s0 + s1) >>> 0) / 0x100000000;
  };
}

/** Sample from triangular distribution. */
export function sampleTriangular(
  min: number,
  mode: number,
  max: number,
  rand: () => number,
): number {
  if (max <= min) return mode;
  const u = rand();
  const fc = (mode - min) / (max - min);
  if (u < fc) {
    return min + Math.sqrt(u * (max - min) * (mode - min));
  }
  return max - Math.sqrt((1 - u) * (max - min) * (max - mode));
}

/** Sample from uniform distribution. */
export function sampleUniform(min: number, max: number, rand: () => number): number {
  return min + rand() * (max - min);
}

/**
 * Sample from PERT (modified beta) distribution.
 * Uses the 4-point approximation: mean = (min + 4*mode + max) / 6
 * Then generates beta-distributed samples via Jöhnk's method.
 */
export function samplePERT(
  min: number,
  mode: number,
  max: number,
  rand: () => number,
  lambda = 4,
): number {
  if (max <= min) return mode;
  const range = max - min;
  const mu = (min + lambda * mode + max) / (lambda + 2);
  const alpha1 = ((mu - min) * (2 * mode - min - max)) / ((mode - mu) * range);
  const alpha2 = (alpha1 * (max - mu)) / (mu - min);

  // If alpha values are invalid, fall back to triangular
  if (alpha1 <= 0 || alpha2 <= 0 || !isFinite(alpha1) || !isFinite(alpha2)) {
    return sampleTriangular(min, mode, max, rand);
  }

  // Generate beta sample using inverse CDF approximation
  const beta = sampleBeta(alpha1, alpha2, rand);
  return min + beta * range;
}

/** Sample from beta distribution using Jöhnk's algorithm. */
function sampleBeta(alpha: number, beta: number, rand: () => number): number {
  // For small alpha/beta, use Jöhnk's method
  if (alpha < 1 && beta < 1) {
    for (;;) {
      const u = Math.pow(rand(), 1 / alpha);
      const v = Math.pow(rand(), 1 / beta);
      const s = u + v;
      if (s <= 1 && s > 0) {
        return u / s;
      }
    }
  }

  // For larger parameters, use gamma ratio method
  const x = sampleGamma(alpha, rand);
  const y = sampleGamma(beta, rand);
  return x / (x + y);
}

/** Sample from gamma distribution using Marsaglia and Tsang's method. */
function sampleGamma(shape: number, rand: () => number): number {
  if (shape < 1) {
    return sampleGamma(shape + 1, rand) * Math.pow(rand(), 1 / shape);
  }
  const d = shape - 1 / 3;
  const c = 1 / Math.sqrt(9 * d);
  for (;;) {
    let x: number;
    let v: number;
    do {
      // Box-Muller for standard normal
      const u1 = rand();
      const u2 = rand();
      x = Math.sqrt(-2 * Math.log(u1 || 1e-10)) * Math.cos(2 * Math.PI * u2);
      v = 1 + c * x;
    } while (v <= 0);
    v = v * v * v;
    const u = rand();
    if (u < 1 - 0.0331 * x * x * x * x) return d * v;
    if (Math.log(u || 1e-10) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
  }
}

// ---------------------------------------------------------------------------
// Simulation engine
// ---------------------------------------------------------------------------

/** Sample a single cost value for one position given its risk parameters. */
function samplePositionCost(param: RiskParameter, rand: () => number): number {
  const min = param.baseCost * param.optimistic;
  const mode = param.baseCost * param.mostLikely;
  const max = param.baseCost * param.pessimistic;

  switch (param.distribution) {
    case 'uniform':
      return sampleUniform(min, max, rand);
    case 'pert':
      return samplePERT(min, mode, max, rand);
    case 'triangular':
    default:
      return sampleTriangular(min, mode, max, rand);
  }
}

/**
 * Run Monte Carlo simulation.
 *
 * @param params     Risk parameters for each BOQ position
 * @param iterations Number of simulation iterations (default 10000)
 * @param seed       Random seed for reproducibility (default Date.now())
 * @param bins       Number of histogram bins (default 40)
 */
export function runSimulation(
  params: RiskParameter[],
  iterations = 10000,
  seed = Date.now(),
  bins = 40,
): SimulationResult {
  if (params.length === 0) {
    return {
      iterations,
      baseTotal: 0,
      percentiles: { p5: 0, p10: 0, p25: 0, p50: 0, p75: 0, p80: 0, p90: 0, p95: 0 },
      mean: 0,
      stdDev: 0,
      contingency: 0,
      contingencyPct: 0,
      histogram: [],
      riskDrivers: [],
    };
  }

  const rand = createRNG(seed);
  const baseTotal = params.reduce((sum, p) => sum + p.baseCost, 0);

  // Run iterations
  const totals = new Float64Array(iterations);
  // Track per-position sums for variance contribution
  const positionSums = params.map(() => new Float64Array(iterations));

  for (let i = 0; i < iterations; i++) {
    let total = 0;
    for (let j = 0; j < params.length; j++) {
      const cost = samplePositionCost(params[j]!, rand);
      positionSums[j]![i] = cost;
      total += cost;
    }
    totals[i] = total;
  }

  // Sort for percentile calculation
  const sorted = Array.from(totals).sort((a, b) => a - b);

  // Percentiles
  const pct = (p: number) => sorted[Math.floor((p / 100) * (iterations - 1))] ?? 0;
  const percentiles = {
    p5: pct(5),
    p10: pct(10),
    p25: pct(25),
    p50: pct(50),
    p75: pct(75),
    p80: pct(80),
    p90: pct(90),
    p95: pct(95),
  };

  // Mean and standard deviation
  let sum = 0;
  for (let i = 0; i < iterations; i++) sum += totals[i]!;
  const mean = sum / iterations;

  let variance = 0;
  for (let i = 0; i < iterations; i++) variance += (totals[i]! - mean) ** 2;
  const stdDev = Math.sqrt(variance / iterations);

  // Contingency
  const contingency = percentiles.p80 - percentiles.p50;
  const contingencyPct = baseTotal > 0 ? (contingency / baseTotal) * 100 : 0;

  // Histogram
  const histMin = sorted[0] ?? 0;
  const histMax = sorted[sorted.length - 1] ?? 0;
  const binWidth = (histMax - histMin) / bins || 1;
  const histogram: HistogramBin[] = [];
  for (let b = 0; b < bins; b++) {
    const binStart = histMin + b * binWidth;
    const binEnd = binStart + binWidth;
    let count = 0;
    for (let i = 0; i < iterations; i++) {
      if (totals[i]! >= binStart && (b === bins - 1 ? totals[i]! <= binEnd : totals[i]! < binEnd)) {
        count++;
      }
    }
    histogram.push({
      binStart,
      binEnd,
      count,
      frequency: count / iterations,
    });
  }

  // Risk drivers: per-position variance contribution
  const totalVariance = variance / iterations;
  const riskDrivers: RiskDriver[] = params.map((param, j) => {
    let posSum = 0;
    const posSums = positionSums[j]!;
    for (let i = 0; i < iterations; i++) posSum += posSums[i]!;
    const posMean = posSum / iterations;
    let posVar = 0;
    for (let i = 0; i < iterations; i++) posVar += (posSums[i]! - posMean) ** 2;
    posVar /= iterations;

    return {
      positionId: param.positionId,
      ordinal: param.ordinal,
      description: param.description,
      baseCost: param.baseCost,
      varianceContribution: posVar,
      contributionPct: totalVariance > 0 ? (posVar / totalVariance) * 100 : 0,
    };
  });

  riskDrivers.sort((a, b) => b.contributionPct - a.contributionPct);

  return {
    iterations,
    baseTotal,
    percentiles,
    mean,
    stdDev,
    contingency,
    contingencyPct,
    histogram,
    riskDrivers,
  };
}

// ---------------------------------------------------------------------------
// Defaults generator
// ---------------------------------------------------------------------------

export interface BOQPositionForRisk {
  id: string;
  ordinal: string;
  description: string;
  quantity: number;
  unit_rate: number;
}

/** Generate default risk parameters from BOQ positions (±15% triangular). */
export function generateDefaultParams(
  positions: BOQPositionForRisk[],
  defaultOptimistic = 0.85,
  defaultPessimistic = 1.25,
  defaultDistribution: DistributionType = 'triangular',
): RiskParameter[] {
  return positions
    .filter((p) => p.quantity > 0 && p.unit_rate > 0)
    .map((p) => ({
      positionId: p.id,
      ordinal: p.ordinal,
      description: p.description,
      baseCost: p.quantity * p.unit_rate,
      optimistic: defaultOptimistic,
      mostLikely: 1.0,
      pessimistic: defaultPessimistic,
      distribution: defaultDistribution,
    }));
}
