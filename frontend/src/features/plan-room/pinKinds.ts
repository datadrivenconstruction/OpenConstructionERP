// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a location pin can point at, and how the pin tool talks to each record module.
 *
 * The pin only references a record; the record keeps its own data. Creating a record from a pin goes
 * through that module's own API, so the module's own write permission and rules apply.
 */

import { createRFI, fetchRFIs } from '@/features/rfi/api';
import { createPunchItem, fetchPunchItems } from '@/features/punchlist/api';
import { createNCR, fetchNCRs } from '@/features/ncr/api';
import { createInspection, fetchInspections } from '@/features/inspections/api';
import type { PinRevisionState, PinTargetKind } from './api';
import { PIN_KIND_COLOR } from './layers';

export interface PinKindMeta {
  kind: PinTargetKind;
  labelKey: string;
  defaultLabel: string;
  color: string;
}

/** The kinds the pin tool offers, in picker order. Photos and observations arrive from their own pages. */
export const PIN_KINDS: PinKindMeta[] = [
  { kind: 'rfi', labelKey: 'plan_room.kind_rfi', defaultLabel: 'RFI', color: PIN_KIND_COLOR.rfi! },
  { kind: 'punch', labelKey: 'plan_room.kind_punch', defaultLabel: 'Punch item', color: PIN_KIND_COLOR.punch! },
  { kind: 'inspection', labelKey: 'plan_room.kind_inspection', defaultLabel: 'Inspection', color: PIN_KIND_COLOR.inspection! },
  { kind: 'ncr', labelKey: 'plan_room.kind_ncr', defaultLabel: 'NCR', color: PIN_KIND_COLOR.ncr! },
  { kind: 'note', labelKey: 'plan_room.kind_note', defaultLabel: 'Note', color: PIN_KIND_COLOR.note! },
];

const ALL_KINDS: PinKindMeta[] = [
  ...PIN_KINDS,
  { kind: 'photo', labelKey: 'plan_room.kind_photo', defaultLabel: 'Photo', color: PIN_KIND_COLOR.photo! },
  { kind: 'observation', labelKey: 'plan_room.kind_observation', defaultLabel: 'Observation', color: PIN_KIND_COLOR.observation! },
];

export const REVISION_STATES: { state: PinRevisionState; labelKey: string; defaultLabel: string }[] = [
  { state: 'current', labelKey: 'plan_room.rev_current', defaultLabel: 'Current sheet' },
  { state: 'carried', labelKey: 'plan_room.rev_carried', defaultLabel: 'Carried to a newer sheet' },
  { state: 'needs_review', labelKey: 'plan_room.rev_needs_review', defaultLabel: 'Needs review' },
  { state: 'orphaned', labelKey: 'plan_room.rev_orphaned', defaultLabel: 'Sheet page gone' },
];

export function kindMeta(kind: PinTargetKind | null | undefined): PinKindMeta {
  return ALL_KINDS.find((k) => k.kind === kind) ?? ALL_KINDS[ALL_KINDS.length - 1]!;
}

/** The page of a record a pin points at, or null for a note (it has no record). */
export function recordPath(kind: PinTargetKind, id: string | null | undefined): string | null {
  if (!id) return null;
  switch (kind) {
    case 'rfi':
      return `/rfi/${id}`;
    case 'punch':
      return `/punchlist?highlight=${id}`;
    case 'ncr':
      return `/ncr?highlight=${id}`;
    case 'inspection':
      return `/inspections?highlight=${id}`;
    default:
      return null;
  }
}

/** The drawing a pin sits on, opened at its page. */
export function sheetPath(documentId: string, page: number): string {
  return `/plan-room?doc=${documentId}&page=${page}`;
}

export interface RecordOption {
  id: string;
  label: string;
}

/** Existing records of a kind the user can link a pin to (first page, newest first as the API orders them). */
export async function listRecordOptions(kind: PinTargetKind, projectId: string): Promise<RecordOption[]> {
  if (!projectId) return [];
  switch (kind) {
    case 'rfi': {
      const page = await fetchRFIs({ project_id: projectId, limit: 100 });
      return page.items.map((r) => ({ id: r.id, label: `${r.rfi_number} ${r.subject}`.trim() }));
    }
    case 'punch': {
      const page = await fetchPunchItems(projectId, { limit: 100 });
      return page.items.map((r) => ({ id: r.id, label: r.title }));
    }
    case 'ncr': {
      const page = await fetchNCRs({ project_id: projectId, limit: 100 });
      return page.items.map((r) => ({ id: r.id, label: `${r.ncr_number} ${r.title}`.trim() }));
    }
    case 'inspection': {
      const page = await fetchInspections({ project_id: projectId });
      return page.items.map((r) => ({ id: r.id, label: `${r.inspection_number} ${r.title}`.trim() }));
    }
    default:
      return [];
  }
}

/** Create a new record of a kind from a pin's title; returns its id. */
export async function createRecordForPin(
  kind: PinTargetKind,
  projectId: string,
  title: string,
  note: string,
): Promise<string | null> {
  const text = note || title;
  switch (kind) {
    case 'rfi':
      return (await createRFI({ project_id: projectId, subject: title, question: text })).id;
    case 'punch':
      return (await createPunchItem({ project_id: projectId, title, description: note })).id;
    case 'ncr':
      return (
        await createNCR({
          project_id: projectId,
          title,
          ncr_type: 'workmanship',
          severity: 'minor',
          description: text,
        })
      ).id;
    case 'inspection':
      return (await createInspection({ project_id: projectId, title, inspection_type: 'general' })).id;
    default:
      return null;
  }
}
