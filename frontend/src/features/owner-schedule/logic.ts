// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { DetectCandidate, DiffChange, Issue } from './api';

/** The best-scoring profile that reads items, or null. The user still confirms it. */
export function bestCandidate(candidates: DetectCandidate[]): DetectCandidate | null {
  const ranked = candidates.filter((c) => c.item_count > 0).sort((a, b) => b.confidence - a.confidence);
  return ranked[0] ?? null;
}

export function hasBlockingIssue(issues: Issue[]): boolean {
  return issues.some((i) => i.severity === 'error');
}

export function countByKind(changes: DiffChange[]): Record<DiffChange['kind'], number> {
  const out = { added: 0, removed: 0, changed: 0, quantity_changed: 0 };
  for (const c of changes) out[c.kind] += 1;
  return out;
}

/** Share of items with a price, 0..100, for the progress bar. */
export function pricedPercent(priced: number, total: number): number {
  return total > 0 ? Math.min(100, Math.round((priced / total) * 100)) : 0;
}
