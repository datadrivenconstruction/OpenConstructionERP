// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure prompt builder for the "Ask AI about this element" action.
 *
 * Turns everything the platform knows about one selected model element (its
 * identity, quantities, classification, linked BOQ position with cost, linked
 * documents, tasks, schedule activities, requirements and validation) into a
 * short natural-language brief plus a closing question. The result pre-seeds
 * the shared AI assistant so a site engineer can send it as-is for a summary,
 * or edit it to ask something specific.
 *
 * Design notes:
 *  - Pure and defensive: every section is optional, so a bare element
 *    (name / type only) still yields a sensible prompt. Never throws.
 *  - Money fields arrive as Decimal strings over the wire even though the
 *    TypeScript type says `number | null`, so they are coerced with `Number`.
 *  - The output is capped well under the assistant's 5000-char input limit.
 *  - No em / en dashes anywhere in the emitted text (house rule).
 */

import type { BIMElementData } from './ElementManager';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/** Longest brief we emit; the assistant hard-caps input at 5000 chars. */
const MAX_PROMPT_CHARS = 4500;

/** Coerce a money value that may arrive as a Decimal string. */
function toNumber(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Compact, locale-aware number formatting (max 2 decimals, no thousands noise). */
function fmt(n: number): string {
  return n.toLocaleString(getNumberLocale(), { maximumFractionDigits: 2 });
}

function nonEmpty(s: string | null | undefined): s is string {
  return typeof s === 'string' && s.trim().length > 0;
}

function boqLine(links: NonNullable<BIMElementData['boq_links']>): string {
  const parts = links.slice(0, 3).map((b) => {
    const head = [b.boq_position_ordinal, b.boq_position_description].filter(nonEmpty).join(' ');
    const qty = toNumber(b.boq_position_quantity);
    const rate = toNumber(b.boq_position_unit_rate);
    const total = toNumber(b.boq_position_total);
    const unit = nonEmpty(b.boq_position_unit) ? ` ${b.boq_position_unit}` : '';
    let cost = '';
    if (qty !== null && rate !== null) {
      cost = `${fmt(qty)}${unit} @ ${fmt(rate)}`;
      if (total !== null) cost += ` = ${fmt(total)}`;
    } else if (total !== null) {
      cost = fmt(total);
    }
    if (head && cost) return `${head} - ${cost}`;
    return head || cost;
  });
  return parts.filter(Boolean).join('; ');
}

/**
 * Build a natural-language brief + question about a single BIM element.
 *
 * @param el - the (ideally context-enriched) selected element.
 * @returns a prompt string, capped at {@link MAX_PROMPT_CHARS} characters.
 */
export function buildElementQuestion(el: BIMElementData): string {
  const lines: string[] = [];
  const label = nonEmpty(el.name) ? el.name : el.element_type || 'this element';

  lines.push('I am on site looking at a model element and want to understand it.');
  lines.push('');

  const idBits: string[] = [];
  if (nonEmpty(el.element_type)) idBits.push(el.element_type);
  if (nonEmpty(el.discipline)) idBits.push(el.discipline);
  if (nonEmpty(el.storey)) idBits.push(`storey ${el.storey}`);
  lines.push(`Element: ${label}${idBits.length ? ` (${idBits.join(', ')})` : ''}`);

  if (el.classification) {
    const cls = Object.entries(el.classification)
      .filter(([, v]) => nonEmpty(v))
      .map(([k, v]) => `${k} ${v}`);
    if (cls.length) lines.push(`Classification: ${cls.join(', ')}`);
  }

  if (el.quantities) {
    const q = Object.entries(el.quantities)
      .filter(([, v]) => typeof v === 'number' && Number.isFinite(v))
      .slice(0, 6)
      .map(([k, v]) => `${k.replace(/_/g, ' ')} ${fmt(v as number)}`);
    if (q.length) lines.push(`Quantities: ${q.join(', ')}`);
  }

  const boq = el.boq_links ?? [];
  if (boq.length) {
    const line = boqLine(boq);
    if (line) lines.push(`Linked BOQ: ${line}`);
  }

  const docs = el.linked_documents ?? [];
  if (docs.length) {
    const names = docs
      .slice(0, 5)
      .map(
        (d) => (nonEmpty(d.document_name) ? d.document_name : d.document_category) || 'document',
      );
    lines.push(`Linked documents: ${names.join(', ')}`);
  }

  const tasks = el.linked_tasks ?? [];
  if (tasks.length) {
    const t = tasks
      .slice(0, 5)
      .map((x) => `${x.title}${nonEmpty(x.status) ? ` (${x.status})` : ''}`);
    lines.push(`Linked tasks: ${t.join(', ')}`);
  }

  const acts = el.linked_activities ?? [];
  if (acts.length) {
    const a = acts.slice(0, 5).map((x) => {
      const bits: string[] = [];
      if (nonEmpty(x.status)) bits.push(x.status);
      if (typeof x.percent_complete === 'number' && Number.isFinite(x.percent_complete)) {
        bits.push(`${Math.round(x.percent_complete)}%`);
      }
      return `${x.name}${bits.length ? ` (${bits.join(', ')})` : ''}`;
    });
    lines.push(`Schedule: ${a.join(', ')}`);
  }

  const reqs = el.linked_requirements ?? [];
  if (reqs.length) {
    const r = reqs.slice(0, 5).map((x) => {
      const spec = [x.entity, x.attribute, x.constraint_type, x.constraint_value, x.unit]
        .filter(nonEmpty)
        .join(' ');
      return `${spec}${nonEmpty(x.status) ? ` [${x.status}]` : ''}`;
    });
    lines.push(`Requirements: ${r.join('; ')}`);
  }

  if (el.validation_status && el.validation_status !== 'unchecked') {
    const findings = (el.validation_results ?? [])
      .slice(0, 5)
      .map((v) => `${v.severity}: ${v.message}`);
    lines.push(
      `Validation: ${el.validation_status}${findings.length ? ` - ${findings.join('; ')}` : ''}`,
    );
  }

  lines.push('');
  lines.push(
    'Please summarise what I should know about this element on site: what it is, ' +
      'its cost, any open tasks or schedule status, and any quality or compliance ' +
      'issues. If anything looks missing or inconsistent, point it out.',
  );

  const out = lines.join('\n');
  return out.length > MAX_PROMPT_CHARS ? `${out.slice(0, MAX_PROMPT_CHARS).trimEnd()}\n...` : out;
}
