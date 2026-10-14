// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the brief screens show for a code: the closed vocabularies, the
// names of catalogue items and the sentences for refusals and findings. The
// vocabularies are written as key maps so a translator finds every key by grep.

import { getErrorMessage } from '@/shared/lib/api';
import type { BadgeVariant } from '@/shared/ui/Badge';

import {
  briefErrorCode,
  briefErrorMessage,
  type BriefStatus,
  type ConceptStatus,
  type ConstraintType,
  type Labelled,
  type Priority,
} from './api';

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
}

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export const BRIEF_STATUS: Record<BriefStatus, KeyText> = {
  draft: ['engineeringBrief.status.draft', 'Draft'],
  in_review: ['engineeringBrief.status.in_review', 'In review'],
  approved: ['engineeringBrief.status.approved', 'Approved'],
  binding: ['engineeringBrief.status.binding', 'Binding'],
  revising: ['engineeringBrief.status.revising', 'Reopened'],
};

export const BRIEF_TONE: Record<BriefStatus, BadgeVariant> = {
  draft: 'neutral',
  in_review: 'purple',
  approved: 'success',
  binding: 'success',
  revising: 'warning',
};

export const PRIORITY_LABEL: Record<Priority, KeyText> = {
  must: ['engineeringBrief.priority.must', 'Must'],
  should: ['engineeringBrief.priority.should', 'Should'],
  could: ['engineeringBrief.priority.could', 'Could'],
  wont: ['engineeringBrief.priority.wont', 'Will not'],
};

export const PRIORITY_TONE: Record<Priority, BadgeVariant> = {
  must: 'error',
  should: 'warning',
  could: 'blue',
  wont: 'neutral',
};

export const CONSTRAINT_LABEL: Record<ConstraintType, KeyText> = {
  equals: ['engineeringBrief.constraint.equals', 'equals'],
  not_equals: ['engineeringBrief.constraint.not_equals', 'does not equal'],
  min: ['engineeringBrief.constraint.min', 'at least'],
  max: ['engineeringBrief.constraint.max', 'at most'],
  range: ['engineeringBrief.constraint.range', 'in range'],
  contains: ['engineeringBrief.constraint.contains', 'contains'],
  not_contains: ['engineeringBrief.constraint.not_contains', 'does not contain'],
  regex: ['engineeringBrief.constraint.regex', 'matches pattern'],
  exists: ['engineeringBrief.constraint.exists', 'is present'],
  not_exists: ['engineeringBrief.constraint.not_exists', 'is absent'],
};

export const CONCEPT_STATUS: Record<ConceptStatus, KeyText> = {
  open: ['engineeringBrief.concept.status.open', 'Open'],
  agreed: ['engineeringBrief.concept.status.agreed', 'Agreed'],
};

export function keyText(t: TFn, entry: KeyText, options?: Record<string, unknown>): string {
  return t(entry[0], { defaultValue: entry[1], ...options });
}

/** Closed vocabularies the server sends as codes: verification methods, originator roles, phases. */
export function vocabularyLabel(t: TFn, group: 'verification' | 'role' | 'phase', code: string): string {
  if (!code) return '';
  return t(group === 'verification' ? `engineering_brief.verification.${code}` : `engineeringBrief.${group}.${code}`, { defaultValue: code.replace(/_/g, ' ') });
}

/** A catalogue item in the reader's language: tenant texts per locale, else the shipped key, else the code. */
export function itemLabel(ctx: LabelContext, item: Labelled | undefined | null, fallback = ''): string {
  if (!item) return fallback;
  const fromLabels = item.labels?.[ctx.language] ?? item.labels?.[ctx.language.split('-')[0] ?? ''] ?? item.labels?.en;
  if (fromLabels) return fromLabels;
  if (item.name_key) return ctx.t(item.name_key, { defaultValue: item.code });
  return item.code || fallback;
}

export function findByCode<T extends Labelled>(items: T[] | undefined, code: string): T | undefined {
  return items?.find((i) => i.code === code);
}

/** A finding in words. The server sends a code, a ref and a detail; the sentence is ours so it follows the locale. */
export function findingText(t: TFn, code: string, detail: string): string {
  return t(`engineering_brief.errors.${code}`, { defaultValue: code.replace(/_/g, ' '), detail });
}

/**
 * The words of a failed call. A refusal shows the server's sentence; our own
 * key for the code is used only when the server wrote none.
 */
export function refusalText(t: TFn, err: unknown): string {
  const code = briefErrorCode(err);
  if (!code) return getErrorMessage(err);
  return briefErrorMessage(err) ?? t(`engineering_brief.errors.${code}`, { defaultValue: code.replace(/_/g, ' ') });
}
