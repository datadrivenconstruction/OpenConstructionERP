// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The rules a letter text obeys, mirrored from backend/app/core/letter_templates.py
 * so the editor can warn while typing. The server runs the same rules on save.
 */

export interface LetterText {
  subject: string;
  heading: string;
  body: string;
  closing: string;
}

export type LetterField = keyof LetterText;

export const LETTER_FIELDS: readonly LetterField[] = ['subject', 'heading', 'body', 'closing'];

export interface LetterPlaceholder {
  name: string;
  sample: string;
  required: boolean;
}

export interface LetterIssue {
  code: 'empty_body' | 'unknown_placeholder' | 'missing_required' | 'too_long';
  severity: 'error' | 'warning';
  field: string;
  placeholder: string;
}

const MAX_LINE = 500;
const MAX_BODY = 20_000;

/** Placeholder names used in a text, in order, without duplicates. */
export function placeholdersIn(text: string): string[] {
  const seen: string[] = [];
  for (const m of (text || '').matchAll(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g)) {
    const name = m[1] ?? '';
    if (name && !seen.includes(name)) seen.push(name);
  }
  return seen;
}

/** Empty body and unknown placeholders are errors; a missing required value is a warning. */
export function checkLetterText(text: LetterText, placeholders: readonly LetterPlaceholder[]): LetterIssue[] {
  const known = new Set(placeholders.map((p) => p.name));
  const issues: LetterIssue[] = [];
  if (!(text.body || '').trim()) {
    issues.push({ code: 'empty_body', severity: 'error', field: 'body', placeholder: '' });
  }
  const used = new Set<string>();
  for (const field of LETTER_FIELDS) {
    const value = text[field] || '';
    if (value.length > (field === 'body' ? MAX_BODY : MAX_LINE)) {
      issues.push({ code: 'too_long', severity: 'error', field, placeholder: '' });
    }
    for (const name of placeholdersIn(value)) {
      used.add(name);
      if (!known.has(name)) issues.push({ code: 'unknown_placeholder', severity: 'error', field, placeholder: name });
    }
  }
  for (const p of placeholders) {
    if (p.required && !used.has(p.name)) {
      issues.push({ code: 'missing_required', severity: 'warning', field: 'body', placeholder: p.name });
    }
  }
  return issues;
}

/** Insert `{name}` at the selection and return the new value and caret. */
export function insertPlaceholder(
  value: string,
  start: number,
  end: number,
  name: string,
): { value: string; caret: number } {
  const token = `{${name}}`;
  const from = Math.max(0, Math.min(start, value.length));
  const to = Math.max(from, Math.min(end, value.length));
  return { value: value.slice(0, from) + token + value.slice(to), caret: from + token.length };
}

export function sameText(a: LetterText, b: LetterText): boolean {
  return LETTER_FIELDS.every((f) => (a[f] || '') === (b[f] || ''));
}
