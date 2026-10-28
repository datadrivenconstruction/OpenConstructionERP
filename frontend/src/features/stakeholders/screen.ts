// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What every stakeholder panel is handed: the project, the pinned framework
// with the server's capability flags, and how to name people and items.

import type { Stakeholder, StakeholderSettings } from './api';
import type { KeyText, LabelContext, TFn } from './labels';

export interface Screen {
  projectId: string;
  settings: StakeholderSettings;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  /** Refetch after a write. */
  onChanged: () => void;
}

export const NAME_FALLBACK: Record<'masked' | 'anonymised' | 'unnamed', KeyText> = {
  masked: ['stakeholders.ui.name.masked', 'Private person (name hidden)'],
  anonymised: ['stakeholders.ui.name.anonymised', 'Anonymised'],
  unnamed: ['stakeholders.ui.name.unnamed', 'Unnamed stakeholder'],
};

/**
 * The name to show for a stakeholder. A private person the caller may not name
 * and an erased contact both say so instead of showing an empty cell.
 */
export function stakeholderName(
  t: TFn,
  s: Pick<Stakeholder, 'name' | 'masked' | 'anonymised'> & { display_name?: string },
): string {
  const key = s.masked ? 'masked' : s.anonymised ? 'anonymised' : null;
  if (key) return t(NAME_FALLBACK[key][0], { defaultValue: NAME_FALLBACK[key][1] });
  return s.name || s.display_name || t(NAME_FALLBACK.unnamed[0], { defaultValue: NAME_FALLBACK.unnamed[1] });
}

/** Names for a list of stakeholder ids, skipping ids the register no longer has. */
export function namesOf(t: TFn, register: readonly Stakeholder[], ids: readonly string[]): string[] {
  const byId = new Map(register.map((s) => [s.id, s]));
  return ids.map((id) => byId.get(id)).filter((s): s is Stakeholder => !!s).map((s) => stakeholderName(t, s));
}
