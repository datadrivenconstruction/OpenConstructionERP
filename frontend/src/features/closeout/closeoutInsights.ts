// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Handover package's contribution to the Module Insights panel.
 *
 * The page already shows a completeness percentage, a delivered-of-required
 * count, a list of gaps and the checklist itself grouped by category. None of
 * that is repeated here. A percentage tells you how far off you are; it does
 * not tell you what kind of problem you have, and closeout has three kinds that
 * look identical in any completeness number:
 *
 * 1. An item nobody has filled at all.
 * 2. An item with a document attached that nobody has checked. It counts as
 *    delivered, and it is the one that embarrasses you at the handover meeting,
 *    because "we have a file" and "someone confirmed it is the right file" are
 *    not the same claim.
 * 3. An item filled by an AI suggestion that no human has confirmed. The
 *    platform proposes bindings, a person is meant to accept them, and a pack
 *    assembled entirely by unreviewed suggestions is not evidence of anything.
 *
 * The charts then cut the remaining gaps two ways the checklist cannot, because
 * the table is grouped by category and can only be read one category at a time.
 * By discipline answers who to chase. By source answers whether chasing is even
 * the right move: a `generated` item is one the platform produces once the
 * upstream work closes, so it is not waiting on a subcontractor's email.
 *
 * Grain is one row per checklist slot. A package holds tens of slots, not
 * thousands, so this stays cheap and needs no request of its own.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { CloseoutSlot } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

/** Same key the checklist's category headers use, so the two always agree. */
function categoryLabel(code: string, t: Translate): string {
  return t(`closeout.category.${code}`, { defaultValue: titleCase(code) });
}

/** Same key the slot's status badge uses. */
function statusLabel(code: string, t: Translate): string {
  return t(`closeout.status.${code}`, { defaultValue: titleCase(code) });
}

/**
 * Where the document has to come from. `generated` is produced by the platform
 * once the upstream register closes; everything else has to be collected from
 * somebody, which is a different kind of chase.
 */
function sourceLabel(code: string, t: Translate): string {
  return t(`closeout.insights.src_${code}`, { defaultValue: titleCase(code) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  slot: string;
  category: string;
  discipline: string;
  status: string;
  source: string;
  obligation: string;
  missing: number;
  unverified: number;
  ai_unchecked: number;
  delivered: number;
}

function toRow(
  s: CloseoutSlot,
  labels: { noDiscipline: string; required: string; optional: string },
  t: Translate,
): Row {
  const b = s.binding;
  // A slot counts as verified only through its status. `bound` means a document
  // is attached and nothing more, which is exactly the gap worth surfacing.
  const bound = s.status === 'bound';
  const verified = s.status === 'verified';

  return {
    slot: s.title,
    category: categoryLabel(s.category, t),
    discipline: s.discipline?.trim() || labels.noDiscipline,
    status: statusLabel(s.status, t),
    source: sourceLabel(s.source_kind, t),
    obligation: s.is_required ? labels.required : labels.optional,
    // Only a required slot can be a gap. An empty optional slot is a choice,
    // not a hole, and counting it would inflate every chase list.
    missing: s.is_required && s.status === 'empty' ? 1 : 0,
    unverified: bound ? 1 : 0,
    ai_unchecked: bound && b?.suggested_by_ai ? 1 : 0,
    delivered: bound || verified ? 1 : 0,
  };
}

export interface CloseoutInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the checklist dataset and its built-in charts. A handover slot records
 * evidence, not money, so there is no currency-formatted measure.
 */
export function buildCloseoutInsights(slots: CloseoutSlot[], t: Translate): CloseoutInsights {
  const labels = {
    noDiscipline: t('closeout.insights.no_discipline', {
      defaultValue: 'Not discipline specific',
    }),
    required: t('closeout.insights.required', { defaultValue: 'Required' }),
    optional: t('closeout.insights.optional', { defaultValue: 'Optional' }),
  };

  const rows: Row[] = [...slots].sort((a, b) => a.ordinal - b.ordinal).map((s) => toRow(s, labels, t));

  const dataset: InsightDataset = {
    id: 'slots',
    label: t('closeout.insights.ds_slots', { defaultValue: 'Handover checklist items' }),
    currency: '',
    fields: [
      { key: 'slot', label: t('closeout.insights.f_slot', { defaultValue: 'Checklist item' }), kind: 'dimension' },
      { key: 'category', label: t('closeout.insights.f_category', { defaultValue: 'Category' }), kind: 'dimension' },
      { key: 'discipline', label: t('closeout.insights.f_discipline', { defaultValue: 'Discipline' }), kind: 'dimension' },
      { key: 'status', label: t('closeout.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'source', label: t('closeout.insights.f_source', { defaultValue: 'Where it comes from' }), kind: 'dimension' },
      { key: 'obligation', label: t('closeout.insights.f_obligation', { defaultValue: 'Required or optional' }), kind: 'dimension' },
      { key: 'missing', label: t('closeout.insights.f_missing', { defaultValue: 'Required and still empty' }), kind: 'measure', format: 'number' },
      { key: 'unverified', label: t('closeout.insights.f_unverified', { defaultValue: 'Attached but not verified' }), kind: 'measure', format: 'number' },
      { key: 'ai_unchecked', label: t('closeout.insights.f_ai_unchecked', { defaultValue: 'AI suggestion not confirmed' }), kind: 'measure', format: 'number' },
      { key: 'delivered', label: t('closeout.insights.f_delivered', { defaultValue: 'Has a document' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'slots', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-missing', title: t('closeout.insights.k_missing', { defaultValue: 'Required items still empty' }), chart: 'kpi', measure: 'missing', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-unverified', title: t('closeout.insights.k_unverified', { defaultValue: 'Attached but not verified' }), chart: 'kpi', measure: 'unverified', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-ai-unchecked', title: t('closeout.insights.k_ai_unchecked', { defaultValue: 'AI suggestions not confirmed' }), chart: 'kpi', measure: 'ai_unchecked', agg: 'sum', color: 2 },
    { ...base, id: 'bar-missing-by-discipline', title: t('closeout.insights.c_missing_by_discipline', { defaultValue: 'Missing items by discipline' }), chart: 'bar', dimension: 'discipline', measure: 'missing', agg: 'sum', color: 1 },
    { ...base, id: 'bar-missing-by-source', title: t('closeout.insights.c_missing_by_source', { defaultValue: 'Missing items by where they come from' }), chart: 'bar', dimension: 'source', measure: 'missing', agg: 'sum', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
