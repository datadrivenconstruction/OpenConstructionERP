// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - paths ("tracks"): the "Start here" answer on the Cases hub.
//
// The hub's filters answer "who am I" (company, role), "where am I" (stage)
// and "where do I work" (market). None of them answers the question a new
// reader actually arrives with, which is "what do I want to get done". With
// three hundred cases, every filter still leaves dozens of equally good
// cards and no first one to open.
//
// A path is a short, curated, ORDERED list of cases for one goal. Picking one
// narrows the list to exactly those cases in the order they are meant to be
// run, so case 1 is the obvious place to start. A path is data, like the
// cases themselves: adding one is adding an entry here, and every id must
// name a shipped case (`tracks.test.ts` holds that).

import type { ComponentType } from 'react';
import {
  Milestone,
  LineChart,
  Compass,
  Calculator,
  HardHat,
  Banknote,
  PackageCheck,
  type LucideProps,
} from 'lucide-react';
import type { CategoryTint } from './categories';

export interface CaseTrack {
  /** Stable id, also the `?track=` value in the hub's address. */
  id: string;
  titleKey: string;
  titleDefault: string;
  /** Who the path is for and what it covers, one sentence. */
  forKey: string;
  forDefault: string;
  icon: ComponentType<LucideProps>;
  /** Tile tint, full literal Tailwind classes (see categories.ts for why). */
  tint: Pick<CategoryTint, 'tile' | 'chip'>;
  /** Case ids in the order they are meant to be run. */
  caseIds: string[];
}

export const CASE_TRACKS: CaseTrack[] = [
  {
    id: 'client-project',
    titleKey: 'cases.track.client_project.title',
    titleDefault: 'Run a project for the client',
    forKey: 'cases.track.client_project.for',
    forDefault:
      'For client-side project managers and owners: phase gates and every management area, from stakeholders to staffing.',
    icon: Milestone,
    tint: {
      tile: 'bg-sky-500/10 text-sky-600 ring-sky-500/20 dark:text-sky-400',
      chip: 'border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300',
    },
    caseIds: [
      'steer-a-client-project-area-by-area',
      'take-a-project-through-a-phase-gate',
      'map-and-engage-the-stakeholders',
      'choose-and-record-the-delivery-model',
      'plan-the-procurement-concept-for-every-package',
      'run-design-management-from-numbering-to-release',
      'plan-permits-and-close-their-conditions',
      'order-long-lead-plant-in-time',
      'plan-site-logistics-for-the-start-gate',
      'staff-the-project-and-clear-people-to-start',
      'set-up-the-quality-concept-before-tender',
      'release-money-before-anyone-commits-it',
    ],
  },
  {
    id: 'cost-control',
    titleKey: 'cases.track.cost_control.title',
    titleDefault: 'Keep cost under control',
    forKey: 'cases.track.cost_control.for',
    forDefault:
      'For cost managers and project controllers: the monthly forecast, commitments, changes and exact payments.',
    icon: LineChart,
    tint: {
      tile: 'bg-emerald-500/10 text-emerald-600 ring-emerald-500/20 dark:text-emerald-400',
      chip: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    },
    caseIds: [
      'run-the-monthly-cost-report',
      'put-every-committed-amount-on-a-cost-line',
      'correct-the-forecast-and-say-why',
      'explain-the-cost-movement-to-the-client',
      'record-payments-and-orders-to-the-cent',
      'control-cost-against-budget',
      'earned-value-and-forecast',
      'cost-value-reconciliation',
      'forecast-project-cash-flow',
    ],
  },
  {
    id: 'first-steps',
    titleKey: 'cases.track.first_steps.title',
    titleDefault: 'First steps on the platform',
    forKey: 'cases.track.first_steps.for',
    forDefault:
      'For anyone new: set up a project and follow one job from the estimate to handover.',
    icon: Compass,
    tint: {
      tile: 'bg-oe-blue/10 text-oe-blue ring-oe-blue/20',
      chip: 'border-oe-blue/40 bg-oe-blue/10 text-oe-blue',
    },
    caseIds: [
      'set-up-a-new-project',
      'estimate-from-cost-database',
      'validate-estimate',
      'project-end-to-end',
    ],
  },
  {
    id: 'estimate-tender',
    titleKey: 'cases.track.estimate_tender.title',
    titleDefault: 'Estimate and tender a job',
    forKey: 'cases.track.estimate_tender.for',
    forDefault: 'For estimators and buyers: quantities, prices, checks and the award.',
    icon: Calculator,
    tint: {
      tile: 'bg-violet-500/10 text-violet-600 ring-violet-500/20 dark:text-violet-400',
      chip: 'border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300',
    },
    caseIds: [
      'takeoff-quantities-from-a-pdf-plan',
      'quantities-from-bim',
      'estimate-from-cost-database',
      'validate-estimate',
      'tender-from-boq',
      'compare-bids-and-award',
    ],
  },
  {
    id: 'run-site',
    titleKey: 'cases.track.run_site.title',
    titleDefault: 'Run the site day to day',
    forKey: 'cases.track.run_site.for',
    forDefault: 'For site managers and foremen: diary, safety, quality and progress.',
    icon: HardHat,
    tint: {
      tile: 'bg-amber-500/10 text-amber-600 ring-amber-500/20 dark:text-amber-400',
      chip: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    },
    caseIds: [
      'run-the-site-day',
      'run-a-safety-walk-and-log-observations',
      'inspect-and-close-ncr',
      'run-a-progress-meeting-and-drive-the-actions',
      'compile-weekly-progress-report',
    ],
  },
  {
    id: 'get-paid',
    titleKey: 'cases.track.get_paid.title',
    titleDefault: 'Get paid for the work',
    forKey: 'cases.track.get_paid.for',
    forDefault: 'For contractors and quantity surveyors: valuations, changes and payment.',
    icon: Banknote,
    tint: {
      tile: 'bg-rose-500/10 text-rose-600 ring-rose-500/20 dark:text-rose-400',
      chip: 'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    },
    caseIds: [
      'prepare-an-interim-payment-application',
      'change-to-paid-variation',
      'payment-application-and-reconciliation',
      'get-paid-on-time-on-a-private-job',
    ],
  },
  {
    id: 'handover',
    titleKey: 'cases.track.handover.title',
    titleDefault: 'Hand over and close out',
    forKey: 'cases.track.handover.for',
    forDefault: 'For project and facility teams: snags, documents and the asset register.',
    icon: PackageCheck,
    tint: {
      tile: 'bg-teal-500/10 text-teal-600 ring-teal-500/20 dark:text-teal-400',
      chip: 'border-teal-500/40 bg-teal-500/10 text-teal-700 dark:text-teal-300',
    },
    caseIds: [
      'clear-the-snag-list-before-handover',
      'as-built-and-om-handover',
      'handover-and-closeout',
      'set-up-the-asset-register-for-fm',
    ],
  },
];

export const TRACK_BY_ID: Record<string, CaseTrack> = Object.fromEntries(
  CASE_TRACKS.map((track) => [track.id, track]),
);

/** The track a `?track=` value names, or null for absent or unknown values. */
export function trackFromParam(raw: string | null | undefined): CaseTrack | null {
  if (!raw) return null;
  return TRACK_BY_ID[raw.trim().toLowerCase()] ?? null;
}

/**
 * Narrow and order a list to one track: only the track's cases, in the track's
 * order. Ids the list does not hold are skipped, so a filter that hides one
 * case shortens the path rather than breaking it.
 */
export function orderByTrack<T extends { id: string }>(list: T[], track: CaseTrack): T[] {
  const byId = new Map(list.map((item) => [item.id, item]));
  const out: T[] = [];
  for (const id of track.caseIds) {
    const item = byId.get(id);
    if (item) out.push(item);
  }
  return out;
}
