// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One resolved, translated description of a module's data paths. The flow
// drawing, the list, the CSV and the SVG/PNG export all read this, so the
// four can never disagree about a number or a label.

import type { TFunction } from 'i18next';

import { formatNumber } from '@/shared/lib/formatters';

import type { Importance, ModulePaths, PathOut, PathState } from './api';
import { moduleMeta } from './moduleMeta';

export interface FlowCard {
  id: string;
  direction: 'in' | 'out';
  module: string;
  moduleLabel: string;
  entityLabel: string;
  count: number | null;
  value: string | null;
  valueText: string | null;
  isMoney: boolean;
  state: PathState;
  staleCount: number | null;
  staleLabel: string | null;
  importance: Importance;
  importanceLabel: string;
  breaksText: string | null;
  active: boolean;
  href: string;
  tone: string;
  /** One line a screen reader or CSV reads, e.g. "From BOQ: 142, 412 300.00". */
  sentence: string;
}

export interface CentreRow {
  id: string;
  label: string;
  count: number | null;
  valueText: string | null;
  value: string | null;
  href: string;
}

export interface ParamRow {
  id: string;
  label: string;
  drives: string[];
  drivesPaths: string[];
  note: string;
}

export interface FlowModel {
  module: string;
  moduleLabel: string;
  why: string | null;
  declared: boolean;
  hasProject: boolean;
  currency: string;
  inputs: FlowCard[];
  outputs: FlowCard[];
  entities: CentreRow[];
  params: ParamRow[];
  tone: string;
}

export function humanize(code: string): string {
  return code
    .replace(/^oe_/, '')
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, (c) => c.toUpperCase());
}

export function moduleLabel(t: TFunction, module: string, fallback?: string): string {
  const meta = moduleMeta(module);
  const def = meta.defaultLabel ?? fallback ?? humanize(module);
  return meta.labelKey ? String(t(meta.labelKey, { defaultValue: def })) : def;
}

function label(t: TFunction, key: string, fallback: string): string {
  return key ? String(t(key, { defaultValue: fallback })) : fallback;
}

const STATE_KEYS: Record<PathState, [string, string]> = {
  ok: ['', ''],
  stale: ['data_paths.state_stale', 'Changed since it was copied'],
  broken: ['data_paths.state_broken', 'Link broken'],
  no_access: ['data_paths.state_no_access', 'No access'],
  not_installed: ['data_paths.state_not_installed', 'Not installed'],
  unknown: ['data_paths.state_unknown', 'Number unavailable'],
  hidden: ['data_paths.state_no_access', 'No access'],
};

export function stateText(t: TFunction, state: PathState): string {
  const [key, def] = STATE_KEYS[state] ?? STATE_KEYS.unknown;
  return key ? String(t(key, { defaultValue: def })) : '';
}

const IMPORTANCE_KEYS: Record<Importance, [string, string]> = {
  critical: ['data_paths.importance_critical', 'Critical'],
  high: ['data_paths.importance_high', 'High'],
  supporting: ['data_paths.importance_supporting', 'Supporting'],
};

function withProject(href: string, projectId: string | null): string {
  if (!href) return '';
  if (!projectId) return href;
  return `${href}${href.includes('?') ? '&' : '?'}project=${encodeURIComponent(projectId)}`;
}

function money(value: string | null, currency: string): string | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return formatNumber(n, currency || undefined);
}

function card(t: TFunction, data: ModulePaths, p: PathOut): FlowCard {
  const modLabel = moduleLabel(t, p.module);
  const entityLabel = label(t, p.label, humanize(p.entity));
  const isMoney = p.measure === 'sum';
  const valueText = isMoney ? money(p.live.value, data.currency) : null;
  const stale = data.stale.find((s) => s.path_id === p.id && (s.count ?? 0) > 0);
  const staleLabel = stale ? label(t, stale.label, 'Changed after it was copied') : null;
  const breaksText = p.breaks ? label(t, p.breaks, '') : null;
  const [ik, idef] = IMPORTANCE_KEYS[p.importance] ?? IMPORTANCE_KEYS.supporting;
  const parts: string[] = [];
  if (p.live.state === 'no_access' || p.live.state === 'not_installed' || p.live.state === 'broken') {
    parts.push(stateText(t, p.live.state));
  } else if (p.live.count !== null && data.project_id) {
    parts.push(`${entityLabel}: ${formatNumber(p.live.count)}`);
    if (valueText) parts.push(valueText);
  } else {
    parts.push(entityLabel);
  }
  if (staleLabel && p.live.stale_count) parts.push(`${staleLabel} (${formatNumber(p.live.stale_count)})`);
  const lead =
    p.direction === 'in'
      ? String(t('data_paths.list_from', { defaultValue: 'From {{module}}', module: modLabel }))
      : String(t('data_paths.list_to', { defaultValue: 'To {{module}}', module: modLabel }));
  return {
    id: p.id,
    direction: p.direction,
    module: p.module,
    moduleLabel: modLabel,
    entityLabel,
    count: data.project_id ? p.live.count : null,
    value: p.live.value,
    valueText,
    isMoney,
    state: p.live.state,
    staleCount: p.live.stale_count,
    staleLabel,
    importance: p.importance,
    importanceLabel: String(t(ik, { defaultValue: idef })),
    breaksText: breaksText || null,
    active: p.live.active,
    href: withProject(p.route || moduleMeta(p.module).route || '', data.project_id),
    tone: moduleMeta(p.module).tone,
    sentence: `${lead}: ${parts.join(', ')}`,
  };
}

export function buildFlowModel(t: TFunction, data: ModulePaths): FlowModel {
  const cards = data.paths.map((p) => card(t, data, p));
  const pathLabel = new Map(cards.map((c) => [c.id, `${c.moduleLabel} (${c.entityLabel})`]));
  return {
    module: data.module,
    moduleLabel: moduleLabel(t, data.module),
    why: data.why ? label(t, data.why, '') || null : null,
    declared: data.declared,
    hasProject: !!data.project_id,
    currency: data.currency,
    inputs: cards.filter((c) => c.direction === 'in'),
    outputs: cards.filter((c) => c.direction === 'out'),
    entities: data.entities.map((e) => ({
      id: e.id,
      label: label(t, e.label, humanize(e.model)),
      count: data.project_id ? e.live.count : null,
      value: e.live.value,
      valueText: e.measure.startsWith('sum') ? money(e.live.value, data.currency) : null,
      href: withProject(e.route, data.project_id),
    })),
    params: data.parameters.map((p, i) => {
      const lbl = label(t, p.label, humanize(p.field.split('.').pop() ?? p.field));
      const targets = p.drives_paths.map((id) => pathLabel.get(id)).filter((x): x is string => !!x);
      return {
        id: `param:${i}`,
        label: lbl,
        drives: p.drives,
        drivesPaths: p.drives_paths,
        note: targets.length ? `${lbl} → ${targets.join(' → ')}` : lbl,
      };
    }),
    tone: moduleMeta(data.module).tone,
  };
}

/** Rows of the List tab and the CSV, in reading order. */
export function listRows(model: FlowModel): { section: 'in' | 'centre' | 'out'; text: string; href: string }[] {
  return [
    ...model.inputs.map((c) => ({ section: 'in' as const, text: c.sentence, href: c.href })),
    ...model.entities.map((e) => ({
      section: 'centre' as const,
      text: [e.label, e.count !== null ? formatNumber(e.count) : null, e.valueText].filter(Boolean).join(', '),
      href: e.href,
    })),
    ...model.outputs.map((c) => ({ section: 'out' as const, text: c.sentence, href: c.href })),
  ];
}
