// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The plain-words reading of one module's paths: which inputs carry data,
// which are empty or broken and what that breaks, in order of importance.

import type { Importance } from './api';
import type { FlowCard, FlowModel } from './flowModel';

export type GapKind = 'empty' | 'broken' | 'not_installed' | 'no_access' | 'stale';

export interface Gap {
  card: FlowCard;
  kind: GapKind;
}

const RANK: Record<Importance, number> = { critical: 0, high: 1, supporting: 2 };

export function byImportance(a: FlowCard, b: FlowCard): number {
  return RANK[a.importance] - RANK[b.importance] || a.moduleLabel.localeCompare(b.moduleLabel);
}

/** Why a path carries nothing useful now, or null when it is fine. */
export function gapOf(card: FlowCard, hasProject: boolean): GapKind | null {
  if (card.state === 'broken') return 'broken';
  if (card.state === 'not_installed') return 'not_installed';
  if (card.state === 'no_access' || card.state === 'hidden') return 'no_access';
  if ((card.staleCount ?? 0) > 0) return 'stale';
  if (hasProject && card.count === 0) return 'empty';
  return null;
}

/** Gaps of inputs and outputs, the most important first; supporting empty paths are not alarms. */
export function findGaps(model: FlowModel): Gap[] {
  const all = [...model.inputs, ...model.outputs].sort(byImportance);
  const out: Gap[] = [];
  for (const card of all) {
    const kind = gapOf(card, model.hasProject);
    if (!kind) continue;
    if (kind === 'empty' && card.importance === 'supporting') continue;
    out.push({ card, kind });
  }
  return out;
}

/** Cards that carry data now, for the story line, strongest first. */
export function liveCards(cards: FlowCard[], hasProject: boolean): FlowCard[] {
  return cards.filter((c) => !gapOf(c, hasProject) && (c.count ?? 0) > 0).sort(byImportance);
}

/** Unique module labels in importance order. */
export function moduleNames(cards: FlowCard[], max = 3): { names: string[]; more: number } {
  const seen: string[] = [];
  for (const c of [...cards].sort(byImportance)) if (!seen.includes(c.moduleLabel)) seen.push(c.moduleLabel);
  return { names: seen.slice(0, max), more: Math.max(0, seen.length - max) };
}
