// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client-side mirror of the server's merge-field checks, so the editor can mark
 * a wrong `{{field}}` while typing. The server stays the authority: publish
 * re-runs every rule.
 */

import type { DocIssue, WordingStatus } from './api';

const TOKEN_RE = /\{\{([^{}\n]{0,120})\}\}/g;
const FIELD_RE = /^\s*([a-z][a-z0-9_]{0,40}(?:\.[a-z][a-z0-9_]{0,40}){0,3})\s*$/;

/** Tokens in `text` that are not one of `known`, as the user wrote them. */
export function unknownFields(text: string, known: ReadonlySet<string>): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(TOKEN_RE)) {
    const path = FIELD_RE.exec(m[1] ?? '')?.[1];
    const shown = path ?? m[0];
    if (!path || !known.has(path)) {
      if (!out.includes(shown)) out.push(shown);
    }
  }
  return out;
}

/** Insert `{{path}}` at the caret, replacing a just-typed `{{`. Returns the new text and caret. */
export function insertField(text: string, caret: number, path: string): { text: string; caret: number } {
  const before = text.slice(0, caret);
  const trimmed = before.endsWith('{{') ? before.slice(0, -2) : before;
  const token = `{{${path}}}`;
  return { text: trimmed + token + text.slice(caret), caret: trimmed.length + token.length };
}

/** Whether a caret position directly follows `{{` (opens the picker). */
export function opensPicker(text: string, caret: number): boolean {
  return text.slice(Math.max(0, caret - 2), caret) === '{{';
}

export function hasBlockingIssue(issues: DocIssue[]): boolean {
  return issues.some((i) => i.severity === 'error');
}

export function sameBlocks(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const key of keys) if ((a[key] ?? '') !== (b[key] ?? '')) return false;
  return true;
}

export const STATUS_VARIANT: Record<WordingStatus, 'neutral' | 'blue' | 'warning' | 'error'> = {
  default: 'neutral',
  custom: 'blue',
  draft: 'warning',
  error: 'error',
};

export const RTL_LANGUAGES = new Set(['ar', 'he', 'fa', 'ur']);

/** Document languages the editor offers: the platform's interface languages, primary subtags. */
export const DOCUMENT_LANGUAGES = [
  'en', 'de', 'fr', 'es', 'it', 'nl', 'pl', 'pt', 'cs', 'ru', 'uk', 'bg', 'hr', 'hu', 'ro', 'el', 'da', 'sv', 'no',
  'fi', 'et', 'tr', 'ar', 'he', 'fa', 'ur', 'hi', 'bn', 'th', 'vi', 'id', 'fil', 'ja', 'ko', 'zh', 'kk', 'ky', 'uz', 'mn',
] as const;
