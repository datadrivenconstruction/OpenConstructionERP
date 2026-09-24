// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { TimelineEntry } from './api';

/** The module a change applied through the AI assistant is logged under. */
export const ASSISTANT_MODULE = 'erp_chat';

/** An in-app path, never another origin: the value comes from the stored row. */
const IN_APP_PATH = /^\/(?![/\\])/;

/**
 * Link for a row the AI assistant applied.
 *
 * Such a row names the domain record it wrote (a BOQ line, a task), not a page
 * of the assistant, so the module-to-route map cannot build it. The record's
 * own link wins when the row carries one in ``metadata.url``; a task is
 * reachable from its project and id alone. Anything else gets no link rather
 * than a guessed one.
 */
export function assistantRecordRoute(entry: TimelineEntry): string | null {
  const url = entry.metadata?.url;
  if (typeof url === 'string' && IN_APP_PATH.test(url)) return url;
  if (entry.entity_type === 'task' && entry.entity_id && entry.parent_entity_id) {
    return `/projects/${entry.parent_entity_id}/tasks?id=${entry.entity_id}`;
  }
  return null;
}
