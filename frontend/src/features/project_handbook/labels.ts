// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the handbook screens show for a code: the chapter statuses, the
// names of chapters, folders and linked records, and the sentences for
// refusals and findings. The vocabularies are written as key maps so a
// translator finds every key by grep.

import { getErrorMessage } from '@/shared/lib/api';
import type { BadgeVariant } from '@/shared/ui/Badge';

import {
  handbookErrorCode,
  handbookErrorMessage,
  type Chapter,
  type ChapterStatus,
  type DataRoomFolder,
  type LinkedRow,
} from './api';

export type TFn = (key: string, options?: Record<string, unknown>) => string;

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export const CHAPTER_STATUS: Record<ChapterStatus, KeyText> = {
  draft: ['projectHandbook.status.draft', 'Draft'],
  in_review: ['projectHandbook.status.in_review', 'In review'],
  approved: ['projectHandbook.status.approved', 'Approved'],
  revising: ['projectHandbook.status.revising', 'Revising'],
};

export const CHAPTER_TONE: Record<ChapterStatus, BadgeVariant> = {
  draft: 'neutral',
  in_review: 'purple',
  approved: 'success',
  revising: 'warning',
};

/** The live sources a chapter can read, by the name the catalogue gives them. */
export const SOURCE_TITLE: Record<string, KeyText> = {
  stakeholders: ['projectHandbook.source.stakeholders', 'Stakeholders'],
  staffing: ['projectHandbook.source.staffing', 'Staffing positions'],
  engineering_brief: ['projectHandbook.source.engineering_brief', 'Framework schedule'],
  governance_gates: ['projectHandbook.source.governance_gates', 'Gates'],
  governance_areas: ['projectHandbook.source.governance_areas', 'Management areas'],
  data_room: ['projectHandbook.source.data_room', 'Data room by area (folders / documents)'],
};

export function keyText(t: TFn, entry: KeyText, options?: Record<string, unknown>): string {
  return t(entry[0], { defaultValue: entry[1], ...options });
}

export function sourceTitle(t: TFn, source: string): string {
  const entry = SOURCE_TITLE[source];
  return entry ? keyText(t, entry) : source.replace(/_/g, ' ');
}

/** A chapter in the reader's language: a retitled chapter keeps its own title, the rest follow the catalogue key. */
export function chapterTitle(t: TFn, chapter: Pick<Chapter, 'title' | 'catalogue_title' | 'title_key' | 'code'>): string {
  if (chapter.title_key && chapter.title === chapter.catalogue_title) {
    return t(chapter.title_key, { defaultValue: chapter.title });
  }
  return chapter.title || chapter.code;
}

/** A catalogue folder translates its key; a folder somebody made by hand prints its own text. */
export function folderName(t: TFn, folder: Pick<DataRoomFolder, 'name' | 'name_key' | 'code'>): string {
  if (folder.name_key) return t(folder.name_key, { defaultValue: folder.name || folder.code });
  return folder.name || folder.code;
}

/** A record of another module: governance entries carry a key, everything else is plain text. */
export function linkedLabel(t: TFn, row: Pick<LinkedRow, 'label' | 'label_key'>): string {
  return row.label_key ? t(row.label_key, { defaultValue: row.label }) : row.label;
}

/** A finding in words. The server sends a code and a ref; the sentence is ours so it follows the locale. */
export function findingText(t: TFn, code: string): string {
  return t(`projectHandbook.finding.${code}`, { defaultValue: code.replace(/_/g, ' ') });
}

/**
 * The words of a failed call. A refusal shows the server's sentence; our own
 * key for the code is used only when the server wrote none.
 */
export function refusalText(t: TFn, err: unknown): string {
  const code = handbookErrorCode(err);
  if (!code) return getErrorMessage(err);
  return handbookErrorMessage(err) ?? t(`project_handbook.errors.${code}`, { defaultValue: code.replace(/_/g, ' ') });
}
