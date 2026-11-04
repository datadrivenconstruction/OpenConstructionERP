// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The record kinds a site manager can raise with no signal, and how each one
 * becomes a queued op.
 *
 * Every kind rides the same field queue (session token, idempotent on
 * `client_op_id`) into the field-diary capture routes; the server hands each
 * capture to the owning module's own service, so no rule is duplicated here.
 */

import type { EnqueueInput, QueuedOp } from '@/shared/lib/offline';
import type { SyncQueueItem } from './syncQueueSummary';

/** Server limit for replaying an offline capture; mirrors field_diary.capture_age. */
export const MAX_OP_AGE_DAYS = 30;

export const KIND_NCR = 'field.ncr';
export const KIND_SAFETY = 'field.safety_observation';
export const KIND_HAUL = 'field.haul_ticket';
/** Field time keeps its own transport (desktop JWT) but is listed beside the rest. */
export const KIND_FIELD_TIME = 'field_time';

export type ReportKind = 'punch' | 'ncr' | 'safety_observation' | 'haul_ticket';
export const REPORT_KINDS: readonly ReportKind[] = ['punch', 'ncr', 'safety_observation', 'haul_ticket'];

const PATHS = {
  ncr: ['/v1/field-diary/capture/ncr/', KIND_NCR],
  safety_observation: ['/v1/field-diary/capture/safety-observation/', KIND_SAFETY],
  haul_ticket: ['/v1/field-diary/capture/haul-ticket/', KIND_HAUL],
} as const;

export interface NcrDraft {
  title: string;
  description: string;
  severity: 'minor' | 'major' | 'critical';
  capturedAt: string;
  lat?: number;
  lon?: number;
}

export interface SafetyDraft {
  observationType: 'positive' | 'unsafe_act' | 'unsafe_condition' | 'near_miss';
  description: string;
  severity: number;
  likelihood: number;
  capturedAt: string;
}

export interface HaulDraft {
  materialName: string;
  netT: string;
  plate: string;
  direction: 'inbound' | 'outbound';
  capturedAt: string;
}

/** A tonnage typed with a comma or spaces; null when it is not a non-negative number. */
export function parseTonnes(raw: string): string | null {
  const cleaned = raw.trim().replace(/\s+/g, '').replace(',', '.');
  if (!/^\d+(\.\d{1,3})?$/.test(cleaned)) return null;
  return cleaned;
}

export function buildNcrOp(draft: NcrDraft, clientOpId: string): EnqueueInput {
  return {
    clientOpId,
    method: 'POST',
    path: PATHS.ncr[0],
    kind: PATHS.ncr[1],
    body: {
      title: draft.title.trim(),
      description: draft.description.trim() || draft.title.trim(),
      severity: draft.severity,
      ncr_type: 'workmanship',
      captured_at: draft.capturedAt,
      lat: draft.lat,
      lon: draft.lon,
    },
  };
}

export function buildSafetyOp(draft: SafetyDraft, clientOpId: string): EnqueueInput {
  return {
    clientOpId,
    method: 'POST',
    path: PATHS.safety_observation[0],
    kind: PATHS.safety_observation[1],
    body: {
      observation_type: draft.observationType,
      description: draft.description.trim(),
      severity: draft.severity,
      likelihood: draft.likelihood,
      captured_at: draft.capturedAt,
    },
  };
}

/** Null when the tonnage is not a number: the form shows the field as wrong instead of queueing it. */
export function buildHaulOp(draft: HaulDraft, clientOpId: string): EnqueueInput | null {
  const net = draft.netT.trim() === '' ? undefined : parseTonnes(draft.netT);
  if (net === null) return null;
  return {
    clientOpId,
    method: 'POST',
    path: PATHS.haul_ticket[0],
    kind: PATHS.haul_ticket[1],
    body: {
      material_name: draft.materialName.trim(),
      net_t: net,
      plate: draft.plate.trim(),
      direction: draft.direction,
      unit: 't',
      captured_at: draft.capturedAt,
    },
  };
}

/** Translation key for a queued op kind, or null when the panel should use its own. */
export function kindLabelKey(kind: string): string | null {
  switch (kind) {
    case KIND_NCR:
      return 'field.report.kind_ncr';
    case KIND_SAFETY:
      return 'field.report.kind_safety_observation';
    case KIND_HAUL:
      return 'field.report.kind_haul_ticket';
    case KIND_FIELD_TIME:
      return 'field.sync_queue.kind_field_time';
    default:
      return null;
  }
}

/**
 * Fold crew-time ops (own queue, own sender) into the one list the panel shows.
 * They are listed and counted with everything else; they replay through their
 * own queue because that one carries the desktop sign-in the field session lacks.
 */
export function fieldTimeAsQueueItems(ops: readonly QueuedOp[]): SyncQueueItem[] {
  return ops.map((op) => ({
    clientOpId: op.clientOpId,
    kind: KIND_FIELD_TIME,
    method: op.method,
    path: op.path,
    queuedAt: op.queuedAt,
    retries: op.retries,
    status: op.retries > 0 ? 'failing' : 'pending',
  }));
}

/** The reason code the server gave for refusing an op, when it is one we explain. */
export function reasonKey(reasonCode: string | undefined): string | null {
  return reasonCode === 'op_too_old' ? 'field.sync_queue.reason_op_too_old' : null;
}
