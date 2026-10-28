// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Names for the records an item or a precondition points at: a gate, a
// management area, a frame document, a funding application. The item stores
// a code or an id; a person picks and reads a name. The lists come from the
// server (`/references`), which reads them from the modules that own them.

import type { Precondition, PreconditionKind, References } from './api';
import { codeLabel, type LabelContext } from './labels';

export interface RefOption {
  value: string;
  label: string;
}

export function gateOptions(refs: References | undefined, ctx: LabelContext): RefOption[] {
  return (refs?.gates ?? []).map((g) => ({ value: g.code, label: codeLabel(ctx, g.code, g.name) }));
}

export function areaOptions(refs: References | undefined, ctx: LabelContext): RefOption[] {
  return (refs?.areas ?? []).map((a) => ({ value: a.code, label: codeLabel(ctx, a.code, a.name) }));
}

/** Two documents of one type differ by the area they belong to, so the area is part of the name. */
export function frameDocumentOptions(refs: References | undefined, ctx: LabelContext): RefOption[] {
  const areas = new Map(areaOptions(refs, ctx).map((a) => [a.value, a.label]));
  return (refs?.frame_documents ?? []).map((d) => {
    const document = codeLabel(ctx, d.doc_type, d.name);
    const area = d.area_code ? areas.get(d.area_code) ?? codeLabel(ctx, d.area_code) : '';
    return {
      value: d.id,
      label: area
        ? ctx.t('commitment.refs.frame_document', { defaultValue: '{{document}} ({{area}})', document, area })
        : document,
    };
  });
}

export function fundingOptions(refs: References | undefined, ctx: LabelContext): RefOption[] {
  return (refs?.funding_applications ?? []).map((f) => ({
    value: f.id,
    label: ctx.t('commitment.refs.funding', { defaultValue: '{{code}} {{title}}', code: f.code, title: f.title }).trim(),
  }));
}

/** The plant item an item already names, as its view carries it. */
export interface StoredPlantItem {
  id: string;
  code: string | null;
}

/**
 * The plant items a commitment item can name. A cancelled one is not offered
 * for a new link, but stays in the list, marked, while it is the one stored.
 * A stored one the register no longer lists stays selectable under its code
 * with a note, so opening and saving the form does not quietly remove it.
 */
export function plantItemOptions(refs: References | undefined, ctx: LabelContext, stored: StoredPlantItem | null): RefOption[] {
  const options: RefOption[] = [];
  for (const p of refs?.plant_items?.items ?? []) {
    const cancelled = p.status === 'cancelled';
    if (cancelled && p.id !== stored?.id) continue;
    options.push({
      value: p.id,
      label: cancelled
        ? ctx.t('commitment.refs.plant_item_cancelled', {
            defaultValue: '{{code}} {{name}} (cancelled)',
            code: p.code,
            name: p.name,
          })
        : ctx.t('commitment.refs.plant_item', { defaultValue: '{{code}} {{name}}', code: p.code, name: p.name }).trim(),
    });
  }
  if (stored && !options.some((o) => o.value === stored.id)) {
    options.push({
      value: stored.id,
      label: stored.code
        ? ctx.t('commitment.refs.plant_item_gone', {
            defaultValue: '{{code}} (no longer in the register)',
            code: stored.code,
          })
        : ctx.t('commitment.refs.plant_item_gone_unnamed', { defaultValue: 'No longer in the register' }),
    });
  }
  return options;
}

/** What a precondition of this kind can point at in this project; empty for kinds that point at nothing. */
export function refOptions(kind: PreconditionKind, refs: References | undefined, ctx: LabelContext): RefOption[] {
  if (kind === 'gate_decided') return gateOptions(refs, ctx);
  if (kind === 'frame_document_binding') return frameDocumentOptions(refs, ctx);
  if (kind === 'funding_approved') return fundingOptions(refs, ctx);
  return [];
}

/**
 * The options of a select that already holds a value. A stored code that the
 * list no longer carries stays selectable under its own name, so opening and
 * saving the form does not quietly clear it.
 */
export function withCurrent(options: RefOption[], value: string, ctx: LabelContext): RefOption[] {
  if (!value || options.some((o) => o.value === value)) return options;
  return [...options, { value, label: codeLabel(ctx, value) }];
}

/** The name of the record a precondition points at, or null when it points at nothing or the record is not listed. */
export function preconditionRefName(
  pre: Pick<Precondition, 'kind' | 'ref_id'>,
  refs: References | undefined,
  ctx: LabelContext,
): string | null {
  if (!pre.ref_id) return null;
  return refOptions(pre.kind, refs, ctx).find((o) => o.value === pre.ref_id)?.label ?? null;
}
