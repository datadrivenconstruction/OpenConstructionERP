// @ts-nocheck
import { describe, it, expect } from 'vitest';
import {
  runSimulation,
  generateDefaultParams,
  sampleTriangular,
  sampleUniform,
  samplePERT,
  createRNG,
  type RiskParameter,
  type BOQPositionForRisk,
} from './data/montecarlo';

// ---------------------------------------------------------------------------
// RNG tests
// ---------------------------------------------------------------------------

describe('createRNG', () => {
  it('produces deterministic sequences from the same seed', () => {
    const rng1 = createRNG(42);
    const rng2 = createRNG(42);
    const seq1 = Array.from({ length: 10 }, rng1);
    const seq2 = Array.from({ length: 10 }, rng2);
    expect(seq1).toEqual(seq2);
  });

  it('produces values between 0 and 1', () => {
    const rng = createRNG(123);
    for (let i = 0; i < 1000; i++) {
      const v = rng();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });

  it('produces different sequences for different seeds', () => {
    const rng1 = createRNG(1);
    const rng2 = createRNG(2);
    const seq1 = Array.from({ length: 5 }, rng1);
    const seq2 = Array.from({ length: 5 }, rng2);
    expect(seq1).not.toEqual(seq2);
  });
});

// ---------------------------------------------------------------------------
// Distribution sampling tests
// ---------------------------------------------------------------------------

describe('sampleTriangular', () => {
  it('produces values within [min, max]', () => {
    const rng = createRNG(42);
    for (let i = 0; i < 500; i++) {
      const v = sampleTriangular(80, 100, 130, rng);
      expect(v).toBeGreaterThanOrEqual(80);
      expect(v).toBeLessThanOrEqual(130);
    }
  });

  it('returns mode when min equals max', () => {
    const rng = createRNG(42);
    const v = sampleTriangular(100, 100, 100, rng);
    expect(v).toBe(100);
  });
});

describe('sampleUniform', () => {
  it('produces values within [min, max]', () => {
    const rng = createRNG(42);
    for (let i = 0; i < 500; i++) {
      const v = sampleUniform(50, 150, rng);
      expect(v).toBeGreaterThanOrEqual(50);
      expect(v).toBeLessThanOrEqual(150);
    }
  });
});

describe('samplePERT', () => {
  it('produces values within [min, max]', () => {
    const rng = createRNG(42);
    for (let i = 0; i < 500; i++) {
      const v = samplePERT(80, 100, 130, rng);
      expect(v).toBeGreaterThanOrEqual(80);
      expect(v).toBeLessThanOrEqual(130);
    }
  });
});

// ---------------------------------------------------------------------------
// generateDefaultParams tests
// ---------------------------------------------------------------------------

describe('generateDefaultParams', () => {
  it('creates params from BOQ positions', () => {
    const positions: BOQPositionForRisk[] = [
      { id: '1', ordinal: '01.001', description: 'Concrete', quantity: 100, unit_rate: 250 },
      { id: '2', ordinal: '01.002', description: 'Rebar', quantity: 5, unit_rate: 1200 },
    ];
    const params = generateDefaultParams(positions);
    expect(params).toHaveLength(2);
    expect(params[0].baseCost).toBe(25000);
    expect(params[0].optimistic).toBe(0.85);
    expect(params[0].pessimistic).toBe(1.25);
    expect(params[1].baseCost).toBe(6000);
  });

  it('filters out zero-cost positions', () => {
    const positions: BOQPositionForRisk[] = [
      { id: '1', ordinal: '01.001', description: 'Free item', quantity: 0, unit_rate: 100 },
      { id: '2', ordinal: '01.002', description: 'Real item', quantity: 10, unit_rate: 50 },
    ];
    const params = generateDefaultParams(positions);
    expect(params).toHaveLength(1);
    expect(params[0].description).toBe('Real item');
  });

  it('uses custom defaults', () => {
    const positions: BOQPositionForRisk[] = [
      { id: '1', ordinal: '01', description: 'Item', quantity: 10, unit_rate: 100 },
    ];
    const params = generateDefaultParams(positions, 0.90, 1.15, 'pert');
    expect(params[0].optimistic).toBe(0.90);
    expect(params[0].pessimistic).toBe(1.15);
    expect(params[0].distribution).toBe('pert');
  });
});

// ---------------------------------------------------------------------------
// runSimulation tests
// ---------------------------------------------------------------------------

describe('runSimulation', () => {
  const sampleParams: RiskParameter[] = [
    {
      positionId: '1',
      ordinal: '01.001',
      description: 'Concrete works',
      baseCost: 50000,
      optimistic: 0.85,
      mostLikely: 1.0,
      pessimistic: 1.30,
      distribution: 'triangular',
    },
    {
      positionId: '2',
      ordinal: '01.002',
      description: 'Steel reinforcement',
      baseCost: 30000,
      optimistic: 0.90,
      mostLikely: 1.0,
      pessimistic: 1.20,
      distribution: 'triangular',
    },
    {
      positionId: '3',
      ordinal: '02.001',
      description: 'Formwork',
      baseCost: 20000,
      optimistic: 0.80,
      mostLikely: 1.0,
      pessimistic: 1.40,
      distribution: 'triangular',
    },
  ];

  it('returns correct base total', () => {
    const result = runSimulation(sampleParams, 1000, 42);
    expect(result.baseTotal).toBe(100000);
  });

  it('runs the requested number of iterations', () => {
    const result = runSimulation(sampleParams, 5000, 42);
    expect(result.iterations).toBe(5000);
  });

  it('produces ordered percentiles', () => {
    const result = runSimulation(sampleParams, 10000, 42);
    const { p5, p10, p25, p50, p75, p80, p90, p95 } = result.percentiles;
    expect(p5).toBeLessThanOrEqual(p10);
    expect(p10).toBeLessThanOrEqual(p25);
    expect(p25).toBeLessThanOrEqual(p50);
    expect(p50).toBeLessThanOrEqual(p75);
    expect(p75).toBeLessThanOrEqual(p80);
    expect(p80).toBeLessThanOrEqual(p90);
    expect(p90).toBeLessThanOrEqual(p95);
  });

  it('computes contingency as P80 - P50', () => {
    const result = runSimulation(sampleParams, 5000, 42);
    expect(result.contingency).toBeCloseTo(
      result.percentiles.p80 - result.percentiles.p50,
      2,
    );
  });

  it('produces non-empty histogram', () => {
    const result = runSimulation(sampleParams, 5000, 42, 20);
    expect(result.histogram.length).toBe(20);
    const totalCount = result.histogram.reduce((s, b) => s + b.count, 0);
    expect(totalCount).toBe(5000);
  });

  it('identifies risk drivers with correct total contribution', () => {
    const result = runSimulation(sampleParams, 5000, 42);
    expect(result.riskDrivers.length).toBe(3);
    const totalContribution = result.riskDrivers.reduce((s, d) => s + d.contributionPct, 0);
    // Sum may slightly exceed 100% due to covariance effects in sampling
    expect(totalContribution).toBeGreaterThan(90);
    expect(totalContribution).toBeLessThan(120);
  });

  it('returns empty result for no params', () => {
    const result = runSimulation([], 1000);
    expect(result.baseTotal).toBe(0);
    expect(result.histogram).toHaveLength(0);
    expect(result.riskDrivers).toHaveLength(0);
  });

  it('produces deterministic results with same seed', () => {
    const r1 = runSimulation(sampleParams, 5000, 42);
    const r2 = runSimulation(sampleParams, 5000, 42);
    expect(r1.percentiles.p50).toBe(r2.percentiles.p50);
    expect(r1.mean).toBe(r2.mean);
  });

  it('P50 is close to base total for symmetric distributions', () => {
    // Symmetric: optimistic 0.85, pessimistic 1.15 (equal distance from 1.0)
    const symmetricParams: RiskParameter[] = [
      {
        positionId: '1',
        ordinal: '01',
        description: 'Symmetric item',
        baseCost: 100000,
        optimistic: 0.85,
        mostLikely: 1.0,
        pessimistic: 1.15,
        distribution: 'triangular',
      },
    ];
    const result = runSimulation(symmetricParams, 50000, 42);
    // P50 should be close to base total (within 5%)
    expect(Math.abs(result.percentiles.p50 - 100000)).toBeLessThan(5000);
  });

  it('works with PERT distribution', () => {
    const pertParams: RiskParameter[] = sampleParams.map((p) => ({
      ...p,
      distribution: 'pert' as const,
    }));
    const result = runSimulation(pertParams, 5000, 42);
    expect(result.percentiles.p50).toBeGreaterThan(0);
    expect(result.histogram.length).toBeGreaterThan(0);
  });

  it('works with uniform distribution', () => {
    const uniformParams: RiskParameter[] = sampleParams.map((p) => ({
      ...p,
      distribution: 'uniform' as const,
    }));
    const result = runSimulation(uniformParams, 5000, 42);
    expect(result.percentiles.p50).toBeGreaterThan(0);
  });
});
