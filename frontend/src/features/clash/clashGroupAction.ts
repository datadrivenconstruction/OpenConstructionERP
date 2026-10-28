// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the "create a work item from a clash group" flow.
 *
 * The clash module clusters raw hits (DBSCAN over centroids) into reviewable
 * groups; this module turns one such group into a single tracked work item
 * (a punch item or a coordination task) in another module, then links back.
 *
 * Everything here is a *pure function* over already-fetched data - no fetch,
 * no React, no side effects - so it is trivially unit-testable and reusable
 * by the page, a dialog and the tests alike. The network calls live in
 * `api.ts` (`clusterActionProposal` / `createClusterAction`).
 */

import type {
  ClashActionTarget,
  ClashCluster,
  ClashGroupActionProposal,
  ClashSeverity,
} from './api';

/** A human-facing band for an AI confidence score (0..1). Drives the chip
 *  colour so a coordinator never confirms a weak guess without noticing. */
export type ConfidenceBand = 'high' | 'medium' | 'low';

/** Bucket a 0..1 confidence score into a presentation band.
 *
 * >= 0.75 → high, >= 0.5 → medium, else low. Out-of-range / NaN inputs are
 * clamped to [0, 1] first so a bad payload never throws.
 */
export function confidenceBand(score: number): ConfidenceBand {
  const s = clamp01(score);
  if (s >= 0.75) return 'high';
  if (s >= 0.5) return 'medium';
  return 'low';
}

/** Clamp a number into [0, 1], mapping NaN/Infinity to 0. */
export function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/** Render a confidence score as a short percentage label, e.g. "82%".
 *  Rounds to the nearest whole percent. */
export function confidenceLabel(score: number): string {
  return `${Math.round(clamp01(score) * 100)}%`;
}

/** Tailwind class set for a confidence chip, keyed by band. Returned as a
 *  single string so the caller can drop it straight onto `className`. */
export function confidenceChipClass(score: number): string {
  switch (confidenceBand(score)) {
    case 'high':
      return 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200';
    case 'medium':
      return 'bg-amber-50 text-amber-700 ring-1 ring-amber-200';
    default:
      return 'bg-rose-50 text-rose-700 ring-1 ring-rose-200';
  }
}

/** Severity → work-item priority, mirroring the backend mapping. A missing
 *  or unknown severity degrades to `medium` (never throws). */
export function severityToPriority(
  severity: ClashSeverity | null | undefined,
): 'low' | 'medium' | 'high' | 'critical' {
  switch (severity) {
    case 'critical':
      return 'critical';
    case 'high':
      return 'high';
    case 'low':
      return 'low';
    default:
      return 'medium';
  }
}

/** A short, human label for one cluster chip, independent of the backend
 *  label string (used as a fallback / for the action dialog header).
 *
 * Examples: "Cluster 3 · MEP x Structural - Level 2 (12)" or, when the
 * cluster has no derived label, "Cluster 3 (12)".
 */
export function clusterChipLabel(cluster: ClashCluster): string {
  const base = (cluster.label || '').trim();
  const suffix = `(${Math.max(0, cluster.size | 0)})`;
  if (base) return `Cluster ${cluster.cluster_id} · ${base} ${suffix}`;
  return `Cluster ${cluster.cluster_id} ${suffix}`;
}

/** One-line summary of a proposal for the confirm dialog / toast.
 *
 * "12 clashes → punch item · high priority · 82% confidence". Degrades
 * cleanly when fields are missing (e.g. no confidence) so it never renders
 * a stray "undefined".
 */
export function summarizeProposal(proposal: ClashGroupActionProposal): string {
  const parts: string[] = [];
  const n = Math.max(0, proposal.member_count | 0);
  const noun = n === 1 ? 'clash' : 'clashes';
  parts.push(`${n} ${noun} → ${targetNoun(proposal.target)}`);
  if (proposal.priority) parts.push(`${proposal.priority} priority`);
  if (Number.isFinite(proposal.confidence)) {
    parts.push(`${confidenceLabel(proposal.confidence)} confidence`);
  }
  return parts.join(' · ');
}

/** Singular noun for a target ("punch item" / "task"), for prose. */
export function targetNoun(target: ClashActionTarget): string {
  return target === 'task' ? 'task' : 'punch item';
}

/** Whether the confirm button should be enabled for a proposal.
 *
 * Disabled when the group is already linked (idempotent no-op) or has no
 * members (nothing to action). Kept here so the page and a dialog agree.
 */
export function canCreateAction(
  proposal: ClashGroupActionProposal | null | undefined,
): boolean {
  if (!proposal) return false;
  if (proposal.already_linked) return false;
  return (proposal.member_count | 0) > 0;
}

/** Group a flat cluster list into reviewable buckets keyed by the dominant
 *  discipline pair, so a long cluster list collapses into trade-pair
 *  sections in the UI. Returns an array of `{ key, label, clusters,
 *  totalSize }`, sorted by total member count desc (biggest coordination
 *  problem first), ties broken by key for determinism.
 *
 * A cluster with no resolved disciplines lands in the `"(mixed)"` bucket.
 */
export interface ClusterPairGroup {
  key: string;
  label: string;
  clusters: ClashCluster[];
  totalSize: number;
}

export function groupClustersByPair(clusters: ClashCluster[]): ClusterPairGroup[] {
  const buckets = new Map<string, ClusterPairGroup>();
  for (const c of clusters) {
    const pair = normalizePair(c.dominant_disciplines);
    const key = pair.length ? pair.join('|') : '(mixed)';
    const label = pair.length ? pair.join(' x ') : '(mixed)';
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { key, label, clusters: [], totalSize: 0 };
      buckets.set(key, bucket);
    }
    bucket.clusters.push(c);
    bucket.totalSize += Math.max(0, c.size | 0);
  }
  return [...buckets.values()].sort(
    (a, b) => b.totalSize - a.totalSize || a.key.localeCompare(b.key),
  );
}

/** Normalise a discipline pair: trim, drop empties, sort so (A,B) === (B,A).
 *  Returns 0, 1 or 2 entries. */
function normalizePair(disciplines: string[] | null | undefined): string[] {
  const cleaned = (disciplines || [])
    .map((d) => (d || '').trim())
    .filter((d) => d.length > 0);
  return [...cleaned].sort((a, b) => a.localeCompare(b)).slice(0, 2);
}
