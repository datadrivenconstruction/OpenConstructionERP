// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - project lifecycle stages, numbering and the derive-from-case helper.
//
// Discipline (categories.ts) says WHAT kind of work a case is; company and role
// say WHO runs it. A lifecycle STAGE says WHEN in a project it happens, from the
// first budget through design, estimating, procurement, planning, construction,
// handover and finally operation. Ordering the whole catalogue along these
// eight stages lets the Cases hub lay the cases out from the start of a project
// to the end and give each one a number, so a user can see where a case sits in
// the journey.
//
// A case rarely names its stage. `stageForPlaybook` derives it from a small
// per-discipline default plus a few explicit overrides for cases whose stage
// differs from their discipline (a feasibility budget is an estimating case but
// happens at the very start; an asset register is a handover case but belongs
// to operation). A data file may set `Playbook.stage` to override outright.
//
// Tint rule mirrors the other axis files: full literal Tailwind class strings.

import {
  Compass,
  DraftingCompass,
  Calculator,
  ShoppingCart,
  CalendarRange,
  HardHat,
  PackageCheck,
  Building2,
  type LucideProps,
} from 'lucide-react';
import type { ComponentType } from 'react';
import type { CaseCategory, LifecycleStage, Playbook } from './types';
import { NEUTRAL_TINT, type CategoryTint } from './categories';

export interface StageMeta {
  id: LifecycleStage;
  /** 1-based position in the lifecycle, shown on the timeline node. */
  num: number;
  labelKey: string;
  labelDefault: string;
  /** One-word label for the compact timeline node. */
  shortKey: string;
  shortDefault: string;
  /** i18n key for the one-line stage description. */
  descKey: string;
  /** One plain line describing what happens in this stage. */
  descDefault: string;
  icon: ComponentType<LucideProps>;
  tint: CategoryTint;
}

/** The eight project lifecycle stages, in order from the start of a project to
 *  the end. Keep ids aligned with the `LifecycleStage` union in `types.ts`. */
export const STAGE_META: StageMeta[] = [
  {
    id: 'define',
    num: 1,
    labelKey: 'cases.stage.define',
    labelDefault: 'Define & brief',
    shortKey: 'cases.stage_short.define',
    shortDefault: 'Define',
    descKey: 'cases.stage_desc.define',
    descDefault: 'Set the project up and test the budget before design.',
    icon: Compass,
    tint: {
      tile: 'bg-slate-500/10 text-slate-600 ring-slate-500/20 dark:text-slate-300',
      chip: 'border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300',
      accent: 'border-l-slate-400/60',
      text: 'text-slate-600 dark:text-slate-300',
    },
  },
  {
    id: 'design',
    num: 2,
    labelKey: 'cases.stage.design',
    labelDefault: 'Design & BIM',
    shortKey: 'cases.stage_short.design',
    shortDefault: 'Design',
    descKey: 'cases.stage_desc.design',
    descDefault: 'Develop and coordinate the design and the models.',
    icon: DraftingCompass,
    tint: {
      tile: 'bg-violet-500/10 text-violet-600 ring-violet-500/20 dark:text-violet-400',
      chip: 'border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300',
      accent: 'border-l-violet-400/60',
      text: 'text-violet-600 dark:text-violet-400',
    },
  },
  {
    id: 'estimate',
    num: 3,
    labelKey: 'cases.stage.estimate',
    labelDefault: 'Estimate & cost plan',
    shortKey: 'cases.stage_short.estimate',
    shortDefault: 'Estimate',
    descKey: 'cases.stage_desc.estimate',
    descDefault: 'Measure, price and plan the cost of the work.',
    icon: Calculator,
    tint: {
      tile: 'bg-amber-500/10 text-amber-600 ring-amber-500/20 dark:text-amber-400',
      chip: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
      accent: 'border-l-amber-400/60',
      text: 'text-amber-600 dark:text-amber-400',
    },
  },
  {
    id: 'procure',
    num: 4,
    labelKey: 'cases.stage.procure',
    labelDefault: 'Tender & procurement',
    shortKey: 'cases.stage_short.procure',
    shortDefault: 'Procure',
    descKey: 'cases.stage_desc.procure',
    descDefault: 'Package, tender and buy the work.',
    icon: ShoppingCart,
    tint: {
      tile: 'bg-emerald-500/10 text-emerald-600 ring-emerald-500/20 dark:text-emerald-400',
      chip: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
      accent: 'border-l-emerald-400/60',
      text: 'text-emerald-600 dark:text-emerald-400',
    },
  },
  {
    id: 'plan',
    num: 5,
    labelKey: 'cases.stage.plan',
    labelDefault: 'Plan & mobilize',
    shortKey: 'cases.stage_short.plan',
    shortDefault: 'Plan',
    descKey: 'cases.stage_desc.plan',
    descDefault: 'Build the programme and get ready to start on site.',
    icon: CalendarRange,
    tint: {
      tile: 'bg-sky-500/10 text-sky-600 ring-sky-500/20 dark:text-sky-400',
      chip: 'border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300',
      accent: 'border-l-sky-400/60',
      text: 'text-sky-600 dark:text-sky-400',
    },
  },
  {
    id: 'build',
    num: 6,
    labelKey: 'cases.stage.build',
    labelDefault: 'Build & control',
    shortKey: 'cases.stage_short.build',
    shortDefault: 'Build',
    descKey: 'cases.stage_desc.build',
    descDefault: 'Run the work on site with quality, safety and cost under control.',
    icon: HardHat,
    tint: {
      tile: 'bg-orange-500/10 text-orange-600 ring-orange-500/20 dark:text-orange-400',
      chip: 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300',
      accent: 'border-l-orange-400/60',
      text: 'text-orange-600 dark:text-orange-400',
    },
  },
  {
    id: 'handover',
    num: 7,
    labelKey: 'cases.stage.handover',
    labelDefault: 'Handover & closeout',
    shortKey: 'cases.stage_short.handover',
    shortDefault: 'Handover',
    descKey: 'cases.stage_desc.handover',
    descDefault: 'Inspect, complete and hand the building over.',
    icon: PackageCheck,
    tint: {
      tile: 'bg-teal-500/10 text-teal-600 ring-teal-500/20 dark:text-teal-400',
      chip: 'border-teal-500/40 bg-teal-500/10 text-teal-700 dark:text-teal-300',
      accent: 'border-l-teal-400/60',
      text: 'text-teal-600 dark:text-teal-400',
    },
  },
  {
    id: 'operate',
    num: 8,
    labelKey: 'cases.stage.operate',
    labelDefault: 'Operate & maintain',
    shortKey: 'cases.stage_short.operate',
    shortDefault: 'Operate',
    descKey: 'cases.stage_desc.operate',
    descDefault: 'Run and maintain the finished building.',
    icon: Building2,
    tint: {
      tile: 'bg-cyan-500/10 text-cyan-600 ring-cyan-500/20 dark:text-cyan-400',
      chip: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
      accent: 'border-l-cyan-400/60',
      text: 'text-cyan-600 dark:text-cyan-400',
    },
  },
];

/** 0-based position of each stage in the lifecycle, for sorting. */
export const STAGE_ORDER: Record<LifecycleStage, number> = Object.fromEntries(
  STAGE_META.map((s, i) => [s.id, i]),
) as Record<LifecycleStage, number>;

/** Fast lookup of a stage's metadata by id. */
export const STAGE_BY_ID: Record<LifecycleStage, StageMeta> = Object.fromEntries(
  STAGE_META.map((s) => [s.id, s]),
) as Record<LifecycleStage, StageMeta>;

/** Where a discipline sits in the lifecycle by default. */
const DEFAULT_STAGE_BY_CATEGORY: Record<CaseCategory, LifecycleStage> = {
  estimating: 'estimate',
  tendering: 'procure',
  bim: 'design',
  planning: 'plan',
  site: 'build',
  quality: 'build',
  commercial: 'build',
  handover: 'handover',
};

/** Cases whose lifecycle stage differs from their discipline default. */
const STAGE_OVERRIDES: Record<string, LifecycleStage> = {
  'set-up-a-new-project': 'define',
  'feasibility-budget-before-design': 'define',
  'set-up-the-asset-register-for-fm': 'operate',
  'defects-liability-period-tracking': 'operate',
};

/** The lifecycle stage a case belongs to: explicit `stage`, then an override,
 *  then the discipline default. */
export function stageForPlaybook(pb: Playbook): LifecycleStage {
  return pb.stage ?? STAGE_OVERRIDES[pb.id] ?? DEFAULT_STAGE_BY_CATEGORY[pb.category] ?? 'build';
}

/** The tint for a stage id, falling back to the neutral tint. */
export function tintForStage(stage: LifecycleStage | undefined): CategoryTint {
  return stage ? (STAGE_BY_ID[stage]?.tint ?? NEUTRAL_TINT) : NEUTRAL_TINT;
}

/**
 * A sequential lifecycle number (1..N) for every case, ordered from the first
 * project stage to the last and, within a stage, by the case's own `order`.
 * Lets the hub show "case 12 of 63" and lay the catalogue out start to finish.
 */
export function buildCaseNumbers(playbooks: Playbook[]): Map<string, number> {
  const sorted = [...playbooks].sort(
    (a, b) =>
      STAGE_ORDER[stageForPlaybook(a)] - STAGE_ORDER[stageForPlaybook(b)] ||
      a.order - b.order ||
      a.id.localeCompare(b.id),
  );
  const numbers = new Map<string, number>();
  sorted.forEach((pb, i) => numbers.set(pb.id, i + 1));
  return numbers;
}
