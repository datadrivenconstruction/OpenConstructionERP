// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for the event-reconciliation API. The reconciliation engine scores
// heterogeneous project records (correspondence, change orders, variations,
// management-of-change entries) and emits explainable links between the records
// that are really about the same underlying event. A reviewer then confirms or
// rejects each suggested link; those decisions are persisted as RecordLink rows.

// The persisted review state of a correlation. "suggested" is a pure engine
// proposal that no one has ruled on yet (no row exists); "confirmed" / "rejected"
// are stored decisions.
export type LinkStatus = 'suggested' | 'confirmed' | 'rejected';

// A reviewer decision. The decision endpoint only accepts these two.
export type LinkDecision = 'confirmed' | 'rejected';

// One record in an assembled event thread, projected onto a uniform shape that
// mirrors the engine's CandidateRecord. record_type / record_id identify the
// source row (e.g. "change_order:<uuid>"); occurred_at is its ISO-8601 timestamp
// or null when the row is undated; refs are the tracked codes (CO-14 etc.) the
// record carries. is_seed marks the record the thread was assembled around.
export interface ThreadRecord {
  record_type: string;
  record_id: string;
  subject: string;
  party: string | null;
  occurred_at: string | null;
  refs: string[];
  is_seed: boolean;
}

// One scored, explainable correlation inside an event thread. Endpoints are the
// engine's canonical (type, id) pairs. confidence is the blended score in [0, 1];
// reasons names every signal that fired (shared_reference / subject_match /
// party_and_date_proximity / embedding_similarity). status is the persisted
// review state, and link_id the persisted row id when a decision exists.
export interface ThreadLink {
  link_id: string | null;
  left_type: string;
  left_id: string;
  right_type: string;
  right_id: string;
  relation: string;
  confidence: number;
  reasons: string[];
  status: LinkStatus;
}

// The reconciled cross-channel thread assembled around one seed event. records is
// the deterministically ordered timeline; links are the scored correlations among
// those records, strongest first; the counts summarise the persisted decisions.
export interface EventThread {
  project_id: string;
  event_key: string;
  seed_type: string | null;
  seed_id: string | null;
  records: ThreadRecord[];
  links: ThreadLink[];
  confirmed_count: number;
  rejected_count: number;
}

// Request to persist a confirm / reject decision on a correlation. The link is
// identified by its canonical endpoints (the same (type, id) pairs the thread
// view returns) and relation; the server re-canonicalises so either argument
// order resolves to the one undirected link. confidence is optional context
// (the engine score at decision time).
export interface RecordLinkDecisionIn {
  left_type: string;
  left_id: string;
  right_type: string;
  right_id: string;
  relation?: string;
  status: LinkDecision;
  confidence?: number | null;
}

// A persisted record-link decision, confidence as a plain float ratio.
// left_subject / right_subject name the two endpoints. The API resolves them
// because a decision outlives the thread it was taken in, so the log has no
// thread on the client to look an id up against; null means the source record
// has since been deleted.
export interface RecordLink {
  id: string;
  project_id: string;
  left_type: string;
  left_id: string;
  left_subject: string | null;
  right_type: string;
  right_id: string;
  right_subject: string | null;
  relation: string;
  confidence: number;
  status: LinkStatus;
  created_by: string | null;
}
