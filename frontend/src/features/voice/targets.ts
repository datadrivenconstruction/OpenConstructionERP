// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Field schemas for the shared voice review UI. These mirror the backend
// voice.structuring target specs exactly (same field names, kinds, and enum
// choices) so the generic review form in <VoiceEntry> can render an editable
// draft for any target with one import. Enum option labels reuse each target
// module's own i18n keys so the words match the rest of that page; a missing
// translation falls back to a humanized token.
//
// Pure and dependency-free (no React, no i18n) so it is trivially unit-testable
// and safe to import anywhere.

import type { VoiceTargetType } from './types';

export type VoiceFieldKind = 'title' | 'text' | 'longtext' | 'enum' | 'date';

export interface VoiceFieldDef {
  /** Field key - must match the backend structuring field name. */
  name: string;
  kind: VoiceFieldKind;
  /** i18n key for the field label (voice.field_*). */
  labelKey: string;
  defaultLabel: string;
  /** Allowed values for `enum` fields (mirrors the backend choices order). */
  choices?: readonly string[];
  /** i18n key for an enum option value, reusing the target module's own keys. */
  optionKey?: (value: string) => string;
  placeholderKey?: string;
  placeholder?: string;
}

export interface VoiceTargetDef {
  target: VoiceTargetType;
  /** i18n key + fallback for the capture trigger / dialog title. */
  titleKey: string;
  defaultTitle: string;
  fields: readonly VoiceFieldDef[];
}

const DIARY_ENTRY_TYPES = [
  'general',
  'delivery',
  'visitor',
  'event',
  'completion',
  'incident_summary',
  'inspection_summary',
  'photo_note',
] as const;

const DEFECT_CATEGORIES = [
  'general',
  'structural',
  'mechanical',
  'electrical',
  'architectural',
  'fire_safety',
  'plumbing',
  'finishing',
  'hvac',
  'exterior',
  'landscaping',
] as const;

const DEFECT_PRIORITIES = ['low', 'medium', 'high', 'critical'] as const;
const TASK_PRIORITIES = ['low', 'normal', 'high', 'urgent'] as const;

export const VOICE_TARGETS: Record<VoiceTargetType, VoiceTargetDef> = {
  diary_note: {
    target: 'diary_note',
    titleKey: 'voice.target_diary',
    defaultTitle: 'Speak a diary note',
    fields: [
      {
        name: 'entry_type',
        kind: 'enum',
        labelKey: 'voice.field_entry_type',
        defaultLabel: 'Entry type',
        choices: DIARY_ENTRY_TYPES,
        optionKey: (v) => `daily_diary.entry_type.${v}`,
      },
      { name: 'title', kind: 'title', labelKey: 'voice.field_title', defaultLabel: 'Title' },
      {
        name: 'description',
        kind: 'longtext',
        labelKey: 'voice.field_description',
        defaultLabel: 'Description',
      },
    ],
  },
  defect: {
    target: 'defect',
    titleKey: 'voice.target_defect',
    defaultTitle: 'Speak a defect',
    fields: [
      { name: 'title', kind: 'title', labelKey: 'voice.field_title', defaultLabel: 'Title' },
      {
        name: 'description',
        kind: 'longtext',
        labelKey: 'voice.field_description',
        defaultLabel: 'Description',
      },
      {
        name: 'location',
        kind: 'text',
        labelKey: 'voice.field_location',
        defaultLabel: 'Location',
      },
      { name: 'trade', kind: 'text', labelKey: 'voice.field_trade', defaultLabel: 'Trade' },
      {
        name: 'category',
        kind: 'enum',
        labelKey: 'voice.field_category',
        defaultLabel: 'Category',
        choices: DEFECT_CATEGORIES,
        optionKey: (v) => `punch.category_${v}`,
      },
      {
        name: 'priority',
        kind: 'enum',
        labelKey: 'voice.field_priority',
        defaultLabel: 'Priority',
        choices: DEFECT_PRIORITIES,
        optionKey: (v) => `punch.priority_${v}`,
      },
    ],
  },
  task: {
    target: 'task',
    titleKey: 'voice.target_task',
    defaultTitle: 'Speak a task',
    fields: [
      { name: 'title', kind: 'title', labelKey: 'voice.field_title', defaultLabel: 'Title' },
      {
        name: 'description',
        kind: 'longtext',
        labelKey: 'voice.field_description',
        defaultLabel: 'Description',
      },
      {
        name: 'priority',
        kind: 'enum',
        labelKey: 'voice.field_priority',
        defaultLabel: 'Priority',
        choices: TASK_PRIORITIES,
        optionKey: (v) => `tasks.priority_${v}`,
      },
      {
        name: 'due_date',
        kind: 'date',
        labelKey: 'voice.field_due_date',
        defaultLabel: 'Due date',
      },
    ],
  },
};

/** Look up the field schema for a target (never throws). */
export function voiceTargetDef(target: VoiceTargetType): VoiceTargetDef {
  return VOICE_TARGETS[target];
}

/** Safe read of one draft field, tolerating a missing key (returns ''). Keeps
 *  consumers clean under `noUncheckedIndexedAccess`. */
export function getField(fields: Record<string, string>, name: string): string {
  const value = fields[name];
  return typeof value === 'string' ? value : '';
}

/** Turn an enum token into a readable fallback label ("fire_safety" ->
 *  "Fire safety") for when no translation exists for the option key. */
export function humanizeToken(value: string): string {
  const spaced = value.replace(/_/g, ' ').trim();
  if (!spaced) return '';
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
