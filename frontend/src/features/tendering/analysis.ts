// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for tendering bid analysis — per-cell outlier flagging
 * and award recommendation classification. Dependency-free so they're
 * easy to unit-test and reuse across the comparison table, recommendation
 * banner, and any future tender export pipeline.
 */

export type CellOutlier = 'high' | 'low' | null;

/**
 * Classify one bid's unit_rate against the row median.
 *
 * Returns ``null`` when fewer than 2 priced bids are available or the
 * cell itself is zero (bid omitted that line). Returns ``'high'`` /
 * ``'low'`` when the rate falls outside ±threshold of the median. Median
 * (not mean) keeps a single extreme bid from skewing the comparison.
 */
export function classifyCell(
  rate: number,
  rowRates: number[],
  threshold = 0.15,
): CellOutlier {
  const priced = rowRates.filter((r) => r > 0);
  if (priced.length < 2 || rate <= 0) return null;
  const sorted = [...priced].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 0
      ? (sorted[mid - 1]! + sorted[mid]!) / 2
      : sorted[mid]!;
  if (median <= 0) return null;
  if (rate >= median * (1 + threshold)) return 'high';
  if (rate <= median * (1 - threshold)) return 'low';
  return null;
}

export interface BidTotalLike {
  bid_id: string;
  company_name: string;
  total: number;
  currency: string;
  deviation_pct: number;
  status: string;
  /** Lines the bidder actually priced (0 = unknown / legacy). */
  matched_lines?: number;
  /** Total reference lines in the package (0 = unknown / legacy). */
  total_lines?: number;
}

export type RecommendationConfidence = 'high' | 'medium' | 'low';

export interface AwardRecommendation {
  winner: BidTotalLike;
  runnerUp: BidTotalLike | null;
  confidence: RecommendationConfidence;
  reasonKey:
    | 'single_bid'
    | 'clear_winner'
    | 'narrow_gap'
    | 'suspicious_low';
  gapAmount: number;
  belowMedianPct: number;
}

/**
 * Recommend a winner among submitted bid totals. ``rejected`` bids are
 * filtered so a previously-declined bidder is never recommended. Returns
 * ``null`` only when no eligible bid exists.
 */
export function recommend(
  totals: BidTotalLike[],
): AwardRecommendation | null {
  const eligible = totals.filter(
    (b) => b.status !== 'rejected' && b.total > 0,
  );
  if (eligible.length === 0) return null;
  const sorted = [...eligible].sort((a, b) => a.total - b.total);
  const winner = sorted[0]!;
  const runnerUp = sorted[1] ?? null;
  const gapAmount = runnerUp ? runnerUp.total - winner.total : 0;

  let belowMedianPct = 0;
  if (eligible.length >= 3) {
    const ms = eligible.map((b) => b.total).sort((a, b) => a - b);
    const mid = Math.floor(ms.length / 2);
    const median =
      ms.length % 2 === 0 ? (ms[mid - 1]! + ms[mid]!) / 2 : ms[mid]!;
    if (median > 0) {
      belowMedianPct = Math.max(0, ((median - winner.total) / median) * 100);
    }
  }

  if (eligible.length === 1) {
    return { winner, runnerUp: null, confidence: 'medium', reasonKey: 'single_bid', gapAmount: 0, belowMedianPct: 0 };
  }
  if (belowMedianPct > 20) {
    return { winner, runnerUp, confidence: 'low', reasonKey: 'suspicious_low', gapAmount, belowMedianPct: Math.round(belowMedianPct * 10) / 10 };
  }
  const gapRatio = runnerUp && winner.total > 0 ? gapAmount / winner.total : 0;
  if (gapRatio < 0.02) {
    return { winner, runnerUp, confidence: 'medium', reasonKey: 'narrow_gap', gapAmount, belowMedianPct: Math.round(belowMedianPct * 10) / 10 };
  }
  // OC-24: an incomplete bid (e.g. 44 of 50 items) should not get "high"
  // confidence. When coverage data is available and below 95%, cap at medium.
  const matched = winner.matched_lines ?? 0;
  const total = winner.total_lines ?? 0;
  if (total > 0 && matched > 0 && matched / total < 0.95) {
    return { winner, runnerUp, confidence: 'medium', reasonKey: 'clear_winner', gapAmount, belowMedianPct: Math.round(belowMedianPct * 10) / 10 };
  }
  return { winner, runnerUp, confidence: 'high', reasonKey: 'clear_winner', gapAmount, belowMedianPct: Math.round(belowMedianPct * 10) / 10 };
}


/** One bidder's cell on a comparison line, as the comparison endpoint sends it. */
export interface BidCellLike {
  unit_rate: number | null;
  /** False when the bidder gave no price for the line. Absent on old answers. */
  priced?: boolean;
}

/**
 * The bidder's unit price on a line, or ``null`` when they gave none.
 *
 * The endpoint sends no figure for an unpriced line (``unit_rate: null``,
 * ``priced: false``). Reading it as 0 would show a missing price exactly like
 * a real zero and rank it the cheapest on the line.
 */
export function cellRate(cell: BidCellLike): number | null {
  if (cell.priced === false || cell.unit_rate === null || cell.unit_rate === undefined) return null;
  return Number(cell.unit_rate);
}

/** The prices on a line that can be compared: the unpriced cells left out. */
export function pricedRates(cells: readonly BidCellLike[]): number[] {
  return cells.map(cellRate).filter((r): r is number => r !== null);
}

/**
 * How many of the package's lines a bid left unpriced, 0 when the comparison
 * carries no coverage (an answer older than ``matched_lines``).
 */
export function unpricedLineCount(bid: Pick<BidTotalLike, 'matched_lines' | 'total_lines'>): number {
  const total = bid.total_lines ?? 0;
  if (total <= 0 || bid.matched_lines === undefined) return 0;
  return Math.max(0, total - bid.matched_lines);
}
