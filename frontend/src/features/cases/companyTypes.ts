// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - company-type metadata and the soft per-group colour palette.
//
// A case can serve several kinds of company (`CompanyType`). This file is the
// single source of truth for the "I work as..." selector on the Cases hub,
// which is the PRIMARY way a user narrows the list (the discipline chips from
// categories.ts stay as a secondary filter). It mirrors categories.ts on
// purpose: the same `CategoryTint` shape, and the same "full literal Tailwind
// class string" rule - Tailwind's JIT only keeps classes it can see as
// complete tokens, so a tint is never built by string concatenation.

import type { ComponentType } from 'react';
import {
  Building2,
  Wrench,
  Calculator,
  Ruler,
  Landmark,
  ClipboardList,
  Boxes,
  KeyRound,
  type LucideProps,
} from 'lucide-react';
import type { CompanyType } from './types';
import { NEUTRAL_TINT, type CategoryTint } from './categories';

export interface CompanyTypeMeta {
  id: CompanyType;
  labelKey: string;
  labelDefault: string;
  /** One short, plain-English line describing who this company type is.
   *  Shown under the label in the "I work as..." selector. Chrome, not case
   *  content, but kept inline (no i18n key) - it is a short descriptive tag
   *  on the selector, not a sentence a translator needs to review on its own. */
  descDefault: string;
  icon: ComponentType<LucideProps>;
  tint: CategoryTint;
}

/** Display order, labels, description, icon and soft tint for each company
 *  type. Keep the ids aligned with the `CompanyType` union in `types.ts`. */
export const COMPANY_TYPE_META: CompanyTypeMeta[] = [
  {
    id: 'general-contractor',
    labelKey: 'cases.company.general_contractor',
    labelDefault: 'General contractor',
    descDefault: 'Runs the site and delivers the whole build',
    icon: Building2,
    tint: {
      tile: 'bg-blue-500/10 text-blue-600 ring-blue-500/20 dark:text-blue-400',
      chip: 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300',
      accent: 'border-l-blue-400/60',
      text: 'text-blue-600 dark:text-blue-400',
    },
  },
  {
    id: 'subcontractor',
    labelKey: 'cases.company.subcontractor',
    labelDefault: 'Specialist subcontractor',
    descDefault: 'Delivers one trade or package under a main contract',
    icon: Wrench,
    tint: {
      tile: 'bg-orange-500/10 text-orange-600 ring-orange-500/20 dark:text-orange-400',
      chip: 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300',
      accent: 'border-l-orange-400/60',
      text: 'text-orange-600 dark:text-orange-400',
    },
  },
  {
    id: 'cost-consultant',
    labelKey: 'cases.company.cost_consultant',
    labelDefault: 'Cost consultancy / QS practice',
    descDefault: 'Prices, measures and controls cost on behalf of a client',
    icon: Calculator,
    tint: {
      tile: 'bg-green-500/10 text-green-600 ring-green-500/20 dark:text-green-400',
      chip: 'border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-300',
      accent: 'border-l-green-400/60',
      text: 'text-green-600 dark:text-green-400',
    },
  },
  {
    id: 'designer',
    labelKey: 'cases.company.designer',
    labelDefault: 'Design / engineering practice',
    descDefault: 'Designs the building and answers the questions it raises',
    icon: Ruler,
    tint: {
      tile: 'bg-purple-500/10 text-purple-600 ring-purple-500/20 dark:text-purple-400',
      chip: 'border-purple-500/40 bg-purple-500/10 text-purple-700 dark:text-purple-300',
      accent: 'border-l-purple-400/60',
      text: 'text-purple-600 dark:text-purple-400',
    },
  },
  {
    id: 'developer-client',
    labelKey: 'cases.company.developer_client',
    labelDefault: 'Developer / client',
    descDefault: 'Commissions the project and carries the budget risk',
    icon: Landmark,
    tint: {
      tile: 'bg-pink-500/10 text-pink-600 ring-pink-500/20 dark:text-pink-400',
      chip: 'border-pink-500/40 bg-pink-500/10 text-pink-700 dark:text-pink-300',
      accent: 'border-l-pink-400/60',
      text: 'text-pink-600 dark:text-pink-400',
    },
  },
  {
    id: 'project-manager',
    labelKey: 'cases.company.project_manager',
    labelDefault: 'Project / construction management firm',
    descDefault: 'Coordinates the programme, the trades and the client',
    icon: ClipboardList,
    tint: {
      tile: 'bg-yellow-500/10 text-yellow-600 ring-yellow-500/20 dark:text-yellow-400',
      chip: 'border-yellow-500/40 bg-yellow-500/10 text-yellow-700 dark:text-yellow-300',
      accent: 'border-l-yellow-400/60',
      text: 'text-yellow-600 dark:text-yellow-400',
    },
  },
  {
    id: 'bim-consultant',
    labelKey: 'cases.company.bim_consultant',
    labelDefault: 'BIM / digital consultancy',
    descDefault: 'Coordinates the models and the digital workflow',
    icon: Boxes,
    tint: {
      tile: 'bg-indigo-500/10 text-indigo-600 ring-indigo-500/20 dark:text-indigo-400',
      chip: 'border-indigo-500/40 bg-indigo-500/10 text-indigo-700 dark:text-indigo-300',
      accent: 'border-l-indigo-400/60',
      text: 'text-indigo-600 dark:text-indigo-400',
    },
  },
  {
    id: 'owner-operator',
    labelKey: 'cases.company.owner_operator',
    labelDefault: 'Owner / operator (FM)',
    descDefault: 'Runs the finished building after handover',
    icon: KeyRound,
    tint: {
      tile: 'bg-cyan-500/10 text-cyan-600 ring-cyan-500/20 dark:text-cyan-400',
      chip: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
      accent: 'border-l-cyan-400/60',
      text: 'text-cyan-600 dark:text-cyan-400',
    },
  },
];

/** Fast lookup of a company type's metadata by id. */
export const COMPANY_TYPE_BY_ID: Record<CompanyType, CompanyTypeMeta> = Object.fromEntries(
  COMPANY_TYPE_META.map((c) => [c.id, c]),
) as Record<CompanyType, CompanyTypeMeta>;

/** The tint for a company type id, falling back to the neutral tint shared
 *  with the discipline chips (see `NEUTRAL_TINT` in `categories.ts`). */
export function tintForCompany(company: CompanyType | undefined): CategoryTint {
  return company ? (COMPANY_TYPE_BY_ID[company]?.tint ?? NEUTRAL_TINT) : NEUTRAL_TINT;
}
