// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Translated words for the spreadsheet import: field names, issue sentences
 * and refusal messages.
 *
 * Issue and refusal texts are looked up by the backend's stable code
 * (`schedule.tabular_import.issue.<code>`, `schedule.tabular_import.error.<code>`).
 * The backend's own English sentence is the fallback, so a code added on the
 * server later still reads as a sentence rather than a key.
 */
import type { TFunction } from 'i18next';

import { issueParams, type ImportErrorDetail, type ImportIssue } from './tabularImport';

const FIELD_DEFAULTS: Record<string, string> = {
  id: 'Activity ID',
  name: 'Activity name',
  wbs: 'WBS code',
  outline_level: 'Outline level',
  start: 'Start',
  finish: 'Finish',
  duration: 'Duration',
  predecessors: 'Predecessors',
  percent_complete: '% complete',
  milestone: 'Milestone',
  resource: 'Resource',
  notes: 'Notes',
  client_visible: 'Visible to client',
};

export function fieldLabel(t: TFunction, field: string): string {
  return t(`schedule.tabular_import.field.${field}`, { defaultValue: FIELD_DEFAULTS[field] ?? field });
}

export function issueText(t: TFunction, issue: ImportIssue): string {
  return t(`schedule.tabular_import.issue.${issue.code}`, {
    ...issueParams(issue.params ?? {}, (field) => fieldLabel(t, field)),
    defaultValue: issue.message,
  });
}

export function errorText(t: TFunction, detail: ImportErrorDetail): string {
  return t(`schedule.tabular_import.error.${detail.code}`, {
    ...issueParams(detail, (field) => fieldLabel(t, field)),
    defaultValue: detail.message,
  });
}
