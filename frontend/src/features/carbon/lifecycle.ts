// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Pure helpers for the life-cycle and company report panels. No DOM, no i18next.

import type { CarbonBudget, CarbonChecks, DataQuality } from './lifecycleApi';

export type Tone = 'success' | 'warning' | 'error' | 'neutral';

/** Budget bar tone: green under 90 %, amber up to 100 %, red over budget. */
export function budgetTone(b: Pick<CarbonBudget, 'budget_kg' | 'used_pct' | 'over_budget'> | undefined): Tone {
  if (!b || Number(b.budget_kg) <= 0) return 'neutral';
  if (b.over_budget) return 'error';
  return b.used_pct >= 90 ? 'warning' : 'success';
}

export function qualityTone(q: DataQuality): Tone {
  if (q === 'measured') return 'success';
  if (q === 'calculated') return 'neutral';
  return 'warning';
}

/** kg as tonnes with one decimal, locale-aware grouping. */
export function kgToTonnes(kg: string | number, locale?: string): string {
  const t = Number(kg) / 1000;
  if (!Number.isFinite(t)) return '0';
  return t.toLocaleString(locale, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
}

export const CHECK_KEYS = ['no_factor', 'outdated_factor_set', 'expired_epd', 'unit_mismatch'] as const;
export type CheckKey = (typeof CHECK_KEYS)[number];

/** Checks with at least one hit, in display order, plus over-budget. */
export function failingChecks(c: CarbonChecks | undefined): Array<{ key: CheckKey | 'over_budget'; count: number }> {
  if (!c) return [];
  const out: Array<{ key: CheckKey | 'over_budget'; count: number }> = CHECK_KEYS.filter(
    (k) => (c[k]?.length ?? 0) > 0,
  ).map((k) => ({ key: k, count: c[k].length }));
  if (c.budget?.over_budget) out.push({ key: 'over_budget', count: 1 });
  return out;
}
