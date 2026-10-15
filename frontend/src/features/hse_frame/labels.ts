// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { TFunction } from 'i18next';

import { fmtList } from '@/shared/lib/formatters';

import type { Catalogue, Duty, Item, ItemStatus, Labelled } from './api';

/** A catalogue entry's label in the reader's language, else English, else its code. */
export function labelOf(entry: Labelled | undefined | null, language: string, fallback = ''): string {
  if (!entry) return fallback;
  const base = (language || 'en').split('-')[0] ?? 'en';
  return entry.labels?.[base] ?? entry.labels?.en ?? entry.code ?? fallback;
}

/** An item that still demands work. */
export function isOpen(status: ItemStatus): boolean {
  return status === 'open' || status === 'in_progress';
}

/** The state of a duty as a stable word for the i18n key and the styling. */
export function dutyWord(duty: Duty): 'yes' | 'no' | 'unknown' {
  if (duty === true) return 'yes';
  return duty === false ? 'no' : 'unknown';
}

/** Items per topic, in the order the catalogue lists its topics; a topic with no item is still listed. */
export function groupByTopic<T extends { topic: string }>(items: T[], topicCodes: string[]): [string, T[]][] {
  const known = new Set(topicCodes);
  const order = [...topicCodes, ...Array.from(new Set(items.map((i) => i.topic))).filter((c) => !known.has(c))];
  return order.map((code) => [code, items.filter((i) => i.topic === code)]);
}

/** Mandatory items done over mandatory items, for the topic header. */
export function progress(items: { obligation: string; status: ItemStatus }[]): { done: number; total: number } {
  const mandatory = items.filter((i) => i.obligation === 'mandatory');
  return { done: mandatory.filter((i) => !isOpen(i.status)).length, total: mandatory.length };
}

/**
 * A register row's title in the reader's language. Rows made from a catalogue template keep the
 * English label as their stored title; while the title is still that label it is shown translated,
 * and a title the user has edited is shown as typed.
 */
export function itemTitle(item: Pick<Item, 'title' | 'template_code'>, catalogue: Pick<Catalogue, 'templates'>, language: string): string {
  if (!item.template_code) return item.title;
  const template = catalogue.templates.find((tpl) => tpl.code === item.template_code);
  if (!template || template.labels?.en !== item.title) return item.title;
  return labelOf(template, language, item.title);
}

/**
 * The bracketed detail of a gate readiness line in the reader's language. The server sends role codes
 * (comma separated) for a role criterion and the word ``no_conditions`` when no permit condition is
 * on file; counts pass through as they are.
 */
export function readinessDetail(
  detail: string,
  catalogue: Pick<Catalogue, 'role_kinds'> | undefined,
  language: string,
  t: TFunction,
): string {
  if (detail === 'no_conditions') return t('hseFrame.readiness.no_conditions', { defaultValue: 'no conditions on file' });
  return fmtList(
    detail.split(',').map((code) => labelOf(catalogue?.role_kinds.find((kind) => kind.code === code), language, code)),
  );
}
