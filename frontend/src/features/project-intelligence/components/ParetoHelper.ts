/**
 * Pareto helper for the Cost Drivers widget (RFC 25).
 *
 * Builds a top-N Pareto dataset ordered by descending share.  The tail (any
 * items past the cut-off) is collapsed into a single "other" bucket so the
 * chart remains readable while still honouring the 100% total.
 *
 * Tie-breaking: items with the exact same share keep the original array's
 * order via a stable ``Array.prototype.sort`` implementation (guaranteed in
 * modern V8).  The ``position_id`` is used as a secondary deterministic key
 * so tests can assert a stable ordering.
 */

export interface ParetoInput {
  position_id: string;
  description?: string | null;
  total_cost?: number | null;
  share_of_total?: number | null;
}

export interface ParetoEntry {
  key: string;
  label: string;
  value: number;
  share: number;
  cumulative: number;
  is_other: boolean;
}

export function buildPareto(items: ParetoInput[], topN = 5): ParetoEntry[] {
  if (!Array.isArray(items) || items.length === 0) return [];

  // Normalise numbers + compute shares if the backend forgot to fill them in.
  const total = items.reduce(
    (acc, item) => acc + (Number(item.total_cost) || 0),
    0,
  );
  const normalised: ParetoEntry[] = items.map((item) => {
    const value = Number(item.total_cost) || 0;
    const share =
      typeof item.share_of_total === 'number' && Number.isFinite(item.share_of_total)
        ? item.share_of_total
        : total > 0
        ? value / total
        : 0;
    return {
      key: item.position_id,
      label: (item.description || item.position_id).slice(0, 80),
      value,
      share,
      cumulative: 0,
      is_other: false,
    };
  });

  normalised.sort((a, b) => {
    if (b.share === a.share) return a.key.localeCompare(b.key);
    return b.share - a.share;
  });

  const top = normalised.slice(0, topN);
  const rest = normalised.slice(topN);

  if (rest.length > 0) {
    const restValue = rest.reduce((acc, r) => acc + r.value, 0);
    const restShare = rest.reduce((acc, r) => acc + r.share, 0);
    top.push({
      key: '__other__',
      label: 'other',
      value: restValue,
      share: restShare,
      cumulative: 0,
      is_other: true,
    });
  }

  let running = 0;
  for (const entry of top) {
    running += entry.share;
    entry.cumulative = running;
  }

  return top;
}
