// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Checklist rows carry no id in the edit payload, but a three-way merge pairs​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * items by id. Before an inspection edit is queued offline, each row is given
 * the id of the stored item with the same question, so the merge sees "this
 * item changed" rather than "one removed, one added". A row whose question was
 * reworded has no match and becomes a new item.
 */

import type { ChecklistEntryPayload, ChecklistItem, UpdateInspectionPayload } from './api';

export type ChecklistEntryWithId = ChecklistEntryPayload & { id: string };

export function checklistWithIds(
  entries: readonly ChecklistEntryPayload[],
  existing: readonly Pick<ChecklistItem, 'id' | 'description'>[],
  newId: () => string = () => `new-${Math.random().toString(36).slice(2, 10)}`,
): ChecklistEntryWithId[] {
  const free = [...existing];
  return entries.map((entry) => {
    const at = free.findIndex((e) => e.description === entry.question);
    if (at >= 0) {
      const [match] = free.splice(at, 1);
      return { ...entry, id: match!.id };
    }
    return { ...entry, id: newId() };
  });
}

/** The online path sends the payload exactly as it always did. */
export function stripChecklistIds(patch: Record<string, unknown>): UpdateInspectionPayload {
  const rows = patch.checklist_data;
  if (!Array.isArray(rows)) return patch as UpdateInspectionPayload;
  return {
    ...(patch as UpdateInspectionPayload),
    checklist_data: rows.map((r) => {
      const { id: _id, ...rest } = r as ChecklistEntryWithId;
      void _id;
      return rest;
    }),
  };
}
