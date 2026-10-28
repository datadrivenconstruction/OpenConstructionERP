// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the BIM Federation health + snapshot/diff surfaces.
 *
 * Everything here is side-effect free and DOM-free so it can be unit
 * tested without React or a browser. The page imports these to render
 * health badges, the diff summary, and the "open all members in 3D"
 * deeplink. Endpoints:
 *
 *   GET  /api/v1/bim-hub/federations/{id}/health
 *   GET  /api/v1/bim-hub/federations/{id}/snapshot
 *   POST /api/v1/bim-hub/federations/{id}/diff   (body = prior snapshot)
 */
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* ── Health types (mirror backend schemas) ─────────────────────────── */

export type FederationMemberHealthState =
  | 'ready'
  | 'processing'
  | 'failed'
  | 'stale'
  | 'missing'
  | 'empty';

export type FederationOverallState =
  | FederationMemberHealthState
  | 'no_members';

export interface FederationMemberHealth {
  member_id: string;
  bim_model_id: string;
  model_name: string;
  discipline: string;
  state: FederationMemberHealthState;
  model_status: string | null;
  element_count: number;
  last_updated: string | null;
  staleness_days: number | null;
  warnings: string[];
}

export interface FederationHealth {
  federation_id: string;
  member_count: number;
  ready_count: number;
  processing_count: number;
  failed_count: number;
  stale_count: number;
  missing_count: number;
  empty_count: number;
  total_elements: number;
  overall_state: FederationOverallState;
  score: number;
  spread_days: number | null;
  members: FederationMemberHealth[];
}

/* ── Snapshot / diff types ─────────────────────────────────────────── */

export interface FederationSnapshotMember {
  bim_model_id: string;
  model_name: string;
  discipline: string;
  element_count: number;
  version?: string | null;
}

export interface FederationSnapshot {
  schema_version: string;
  federation_id: string;
  name: string;
  captured_at: string;
  member_count: number;
  total_elements: number;
  members: FederationSnapshotMember[];
}

export interface FederationSnapshotMemberDelta {
  bim_model_id: string;
  model_name: string;
  discipline: string;
  element_count_delta: number;
  old_element_count: number;
  new_element_count: number;
}

export interface FederationDiff {
  federation_id: string;
  old_captured_at: string;
  new_captured_at: string;
  added: FederationSnapshotMember[];
  removed: FederationSnapshotMember[];
  changed: FederationSnapshotMemberDelta[];
  unchanged: FederationSnapshotMember[];
  total_element_drift: number;
}

/* ── Health presentation helpers ───────────────────────────────────── */

export type HealthTone = 'green' | 'amber' | 'red' | 'neutral';

/**
 * Traffic-light tone for a member/overall state. ``ready`` is green;
 * ``stale``/``empty``/``processing`` are amber (attention, not broken);
 * ``failed``/``missing`` are red; ``no_members`` is neutral.
 */
export function toneForState(state: FederationOverallState): HealthTone {
  switch (state) {
    case 'ready':
      return 'green';
    case 'stale':
    case 'empty':
    case 'processing':
      return 'amber';
    case 'failed':
    case 'missing':
      return 'red';
    default:
      return 'neutral';
  }
}

/** i18n key suffix for a state label, e.g. ``ready`` -> ``state_ready``. */
export function stateLabelKey(state: FederationOverallState): string {
  return `state_${state}`;
}

/**
 * Readiness percentage (0..100, integer) from a 0..1 score. Defensive
 * against out-of-range / NaN scores so the UI never prints "NaN%".
 */
export function readinessPercent(score: number): number {
  if (!Number.isFinite(score)) return 0;
  const clamped = Math.max(0, Math.min(1, score));
  return Math.round(clamped * 100);
}

/**
 * Whether a health report has anything the coordinator should act on
 * (anything that is not a clean all-ready set). Drives the warning
 * banner visibility.
 */
export function hasActionableIssues(health: FederationHealth | undefined): boolean {
  if (!health) return false;
  return (
    health.processing_count > 0 ||
    health.failed_count > 0 ||
    health.stale_count > 0 ||
    health.missing_count > 0 ||
    health.empty_count > 0
  );
}

/**
 * Ordered list of non-zero issue buckets, worst first, for a compact
 * summary line. Returns ``[{ state, count }]`` so the caller can i18n
 * each label. Excludes ``ready`` (not an issue).
 */
export function issueBreakdown(
  health: FederationHealth | undefined,
): Array<{ state: FederationMemberHealthState; count: number }> {
  if (!health) return [];
  const order: Array<[FederationMemberHealthState, number]> = [
    ['missing', health.missing_count],
    ['failed', health.failed_count],
    ['processing', health.processing_count],
    ['empty', health.empty_count],
    ['stale', health.stale_count],
  ];
  return order
    .filter(([, count]) => count > 0)
    .map(([state, count]) => ({ state, count }));
}

/* ── Deeplink: open every member in the BIM viewer ─────────────────── */

/**
 * Build a deeplink that opens the federation's first member in the BIM
 * viewer with the remaining members passed as a ``models`` query param
 * and the originating federation as ``federation``. The viewer can load
 * the extra models as overlays; if it ignores the params it still opens
 * the primary model, so the link degrades gracefully.
 *
 * Returns ``null`` when there are no members to open.
 */
export function buildFederationViewerDeeplink(
  federationId: string,
  memberModelIds: string[],
): string | null {
  const [primary, ...rest] = memberModelIds;
  if (primary === undefined) return null;
  const params = new URLSearchParams();
  params.set('federation', federationId);
  if (rest.length > 0) params.set('models', rest.join(','));
  return `/bim/${encodeURIComponent(primary)}?${params.toString()}`;
}

/* ── Snapshot file naming + parsing ────────────────────────────────── */

/**
 * Deterministic, filesystem-safe filename for a downloaded snapshot, e.g.
 * ``federation-coordination-set-2026-06-06.json``. Non-alphanumerics in
 * the name collapse to single hyphens.
 */
export function snapshotFileName(snapshot: FederationSnapshot): string {
  const slug = (snapshot.name || 'federation')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
  const day = (snapshot.captured_at || '').slice(0, 10) || 'snapshot';
  return `federation-${slug || 'federation'}-${day}.json`;
}

/**
 * Validate that an arbitrary parsed JSON object looks like a federation
 * snapshot before we send it to the diff endpoint. Returns the typed
 * snapshot on success, or throws a coded Error the UI can translate.
 *
 * Codes: ``invalid_json_shape`` (not an object / missing keys),
 * ``schema_version_unsupported``.
 */
export function parseSnapshotPayload(raw: unknown): FederationSnapshot {
  if (typeof raw !== 'object' || raw === null) {
    throw new Error('invalid_json_shape');
  }
  const obj = raw as Record<string, unknown>;
  if (
    typeof obj.federation_id !== 'string' ||
    typeof obj.captured_at !== 'string' ||
    !Array.isArray(obj.members)
  ) {
    throw new Error('invalid_json_shape');
  }
  if (obj.schema_version !== undefined && obj.schema_version !== '1') {
    throw new Error('schema_version_unsupported');
  }
  return raw as FederationSnapshot;
}

/**
 * Whether an uploaded snapshot belongs to the federation being diffed.
 * Cross-federation diffs are nonsensical (the model ids would all read as
 * added/removed), so the UI blocks them up front.
 */
export function snapshotMatchesFederation(
  snapshot: FederationSnapshot,
  federationId: string,
): boolean {
  return snapshot.federation_id === federationId;
}

/* ── Diff summary ──────────────────────────────────────────────────── */

/**
 * One-line, i18n-ready summary counts for a diff. Returns raw numbers so
 * the caller owns the wording (and pluralisation) per locale.
 */
export function diffSummaryCounts(diff: FederationDiff): {
  added: number;
  removed: number;
  changed: number;
  unchanged: number;
  drift: number;
} {
  return {
    added: diff.added.length,
    removed: diff.removed.length,
    changed: diff.changed.length,
    unchanged: diff.unchanged.length,
    drift: diff.total_element_drift,
  };
}

/** Whether a diff shows any composition or element-count change at all. */
export function diffHasChanges(diff: FederationDiff): boolean {
  return (
    diff.added.length > 0 ||
    diff.removed.length > 0 ||
    diff.changed.length > 0 ||
    diff.total_element_drift !== 0
  );
}

/**
 * Signed, locale-free drift label, e.g. ``+1 240`` / ``-37`` / ``0``.
 * The caller wraps it with a translated "elements" suffix.
 */
export function formatDrift(drift: number): string {
  const sign = drift > 0 ? '+' : '';
  return `${sign}${drift.toLocaleString(getNumberLocale())}`;
}
