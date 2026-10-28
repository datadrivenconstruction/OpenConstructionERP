// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - professional-role metadata, avatar recipe and the derive-from-case
// helper.
//
// `CompanyType` (companyTypes.ts) is the PRIMARY axis on the Cases hub: what
// kind of firm you are. `ProfessionalRole` is one level finer: what you
// personally do inside that firm. A general contractor employs an estimator, a
// site manager and a foreman at once, and each of them wants a different slice
// of the same case list. This file is the single source of truth for the "Your
// role" selector, which renders an illustrated persona avatar per role
// (see RoleAvatar.tsx) so the choice reads at a glance.
//
// A case almost never names its roles. `rolesForPlaybook` derives them from the
// case discipline (`category`) and the company types it serves, so every one of
// the existing cases gets a sensible role set with no per-file edits. A data
// file may still set `Playbook.roles` explicitly to override the derivation.
//
// Tint rule mirrors categories.ts / companyTypes.ts: full literal Tailwind
// class strings only (JIT keeps complete tokens, never concatenated ones).

import {
  Calculator,
  Ruler,
  ClipboardCheck,
  Network,
  Boxes,
  ShoppingCart,
  CalendarRange,
  ShieldCheck,
  DraftingCompass,
  FolderOpen,
  Handshake,
  Receipt,
  ScrollText,
  Banknote,
  Megaphone,
  type LucideProps,
} from 'lucide-react';
import type { ComponentType } from 'react';
import type { CaseCategory, CompanyType, Playbook, ProfessionalRole } from './types';
import { NEUTRAL_TINT, type CategoryTint } from './categories';

/** How the persona in the avatar is dressed. Drives the head-gear overlay in
 *  RoleAvatar.tsx: a hard hat for field roles, a headset for coordinators,
 *  safety glasses for technical/design roles, or a bare head for office roles
 *  (which are then told apart by their badge icon and colour). */
export type RoleHeadgear = 'hardhat' | 'headset' | 'glasses' | 'none';

export interface RoleMeta {
  id: ProfessionalRole;
  labelKey: string;
  labelDefault: string;
  /** One short plain-English line describing the role, shown under the label
   *  in the selector. Chrome, kept inline (no standalone i18n key) like the
   *  company-type descriptions. */
  descDefault: string;
  /** Head-gear the avatar persona wears. */
  headgear: RoleHeadgear;
  /** Small lucide glyph shown on the avatar's role badge (bottom-right). */
  badge: ComponentType<LucideProps>;
  /** Soft tint used by the selector button and card role chips. */
  tint: CategoryTint;
  /** `text-*` colour (light + dark) painting the persona silhouette via
   *  `currentColor`. Kept as its own literal so the avatar is coloured
   *  independently of the tile/chip tints above. */
  avatarText: string;
  /** Case disciplines this role runs. Used to derive role relevance for cases
   *  that do not set `roles` explicitly. */
  categories: CaseCategory[];
  /** Company types that always imply this role, regardless of discipline
   *  (e.g. any designer-facing case is relevant to the design lead). */
  companyTypes?: CompanyType[];
}

/** Display order, labels, avatar recipe, tint and case affinity for each
 *  professional role. Keep ids aligned with the `ProfessionalRole` union. */
export const ROLE_META: RoleMeta[] = [
  {
    id: 'estimator',
    labelKey: 'cases.role.estimator',
    labelDefault: 'Estimator',
    descDefault: 'Prices the work and builds the bill',
    headgear: 'none',
    badge: Calculator,
    avatarText: 'text-amber-600 dark:text-amber-400',
    tint: {
      tile: 'bg-amber-500/10 text-amber-600 ring-amber-500/20 dark:text-amber-400',
      chip: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
      accent: 'border-l-amber-400/60',
      text: 'text-amber-600 dark:text-amber-400',
    },
    categories: ['estimating', 'tendering'],
  },
  {
    id: 'quantity-surveyor',
    labelKey: 'cases.role.quantity_surveyor',
    labelDefault: 'Quantity surveyor',
    descDefault: 'Measures, values and controls the money',
    headgear: 'none',
    badge: Ruler,
    avatarText: 'text-teal-600 dark:text-teal-400',
    tint: {
      tile: 'bg-teal-500/10 text-teal-600 ring-teal-500/20 dark:text-teal-400',
      chip: 'border-teal-500/40 bg-teal-500/10 text-teal-700 dark:text-teal-300',
      accent: 'border-l-teal-400/60',
      text: 'text-teal-600 dark:text-teal-400',
    },
    categories: ['estimating', 'commercial', 'tendering'],
  },
  {
    id: 'site-manager',
    labelKey: 'cases.role.site_manager',
    labelDefault: 'Site manager',
    descDefault: 'Runs the work on the ground day to day',
    headgear: 'hardhat',
    badge: ClipboardCheck,
    avatarText: 'text-orange-600 dark:text-orange-400',
    tint: {
      tile: 'bg-orange-500/10 text-orange-600 ring-orange-500/20 dark:text-orange-400',
      chip: 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300',
      accent: 'border-l-orange-400/60',
      text: 'text-orange-600 dark:text-orange-400',
    },
    categories: ['site', 'quality', 'planning'],
  },
  {
    id: 'project-manager',
    labelKey: 'cases.role.project_manager',
    labelDefault: 'Project manager',
    descDefault: 'Coordinates programme, trades and client',
    headgear: 'headset',
    badge: Network,
    avatarText: 'text-blue-600 dark:text-blue-400',
    tint: {
      tile: 'bg-blue-500/10 text-blue-600 ring-blue-500/20 dark:text-blue-400',
      chip: 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300',
      accent: 'border-l-blue-400/60',
      text: 'text-blue-600 dark:text-blue-400',
    },
    categories: ['planning', 'site', 'commercial', 'handover'],
  },
  {
    id: 'bim-coordinator',
    labelKey: 'cases.role.bim_coordinator',
    labelDefault: 'BIM coordinator',
    descDefault: 'Runs the models and the digital workflow',
    headgear: 'glasses',
    badge: Boxes,
    avatarText: 'text-violet-600 dark:text-violet-400',
    tint: {
      tile: 'bg-violet-500/10 text-violet-600 ring-violet-500/20 dark:text-violet-400',
      chip: 'border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300',
      accent: 'border-l-violet-400/60',
      text: 'text-violet-600 dark:text-violet-400',
    },
    categories: ['bim'],
  },
  {
    id: 'procurement-buyer',
    labelKey: 'cases.role.procurement_buyer',
    labelDefault: 'Procurement / buyer',
    descDefault: 'Packages, tenders and buys the work',
    headgear: 'none',
    badge: ShoppingCart,
    avatarText: 'text-emerald-600 dark:text-emerald-400',
    tint: {
      tile: 'bg-emerald-500/10 text-emerald-600 ring-emerald-500/20 dark:text-emerald-400',
      chip: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
      accent: 'border-l-emerald-400/60',
      text: 'text-emerald-600 dark:text-emerald-400',
    },
    categories: ['tendering', 'commercial'],
  },
  {
    id: 'planner',
    labelKey: 'cases.role.planner',
    labelDefault: 'Planner / scheduler',
    descDefault: 'Builds and tracks the programme',
    headgear: 'none',
    badge: CalendarRange,
    avatarText: 'text-sky-600 dark:text-sky-400',
    tint: {
      tile: 'bg-sky-500/10 text-sky-600 ring-sky-500/20 dark:text-sky-400',
      chip: 'border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300',
      accent: 'border-l-sky-400/60',
      text: 'text-sky-600 dark:text-sky-400',
    },
    categories: ['planning'],
  },
  {
    id: 'hse-officer',
    labelKey: 'cases.role.hse_officer',
    labelDefault: 'Health & safety officer',
    descDefault: 'Keeps the site safe and compliant',
    headgear: 'hardhat',
    badge: ShieldCheck,
    avatarText: 'text-red-600 dark:text-red-400',
    tint: {
      tile: 'bg-red-500/10 text-red-600 ring-red-500/20 dark:text-red-400',
      chip: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
      accent: 'border-l-red-400/60',
      text: 'text-red-600 dark:text-red-400',
    },
    categories: ['site', 'quality'],
  },
  {
    id: 'design-lead',
    labelKey: 'cases.role.design_lead',
    labelDefault: 'Design lead',
    descDefault: 'Owns the design and its coordination',
    headgear: 'glasses',
    badge: DraftingCompass,
    avatarText: 'text-purple-600 dark:text-purple-400',
    tint: {
      tile: 'bg-purple-500/10 text-purple-600 ring-purple-500/20 dark:text-purple-400',
      chip: 'border-purple-500/40 bg-purple-500/10 text-purple-700 dark:text-purple-300',
      accent: 'border-l-purple-400/60',
      text: 'text-purple-600 dark:text-purple-400',
    },
    categories: ['bim', 'estimating'],
    companyTypes: ['designer'],
  },
  {
    id: 'document-controller',
    labelKey: 'cases.role.document_controller',
    labelDefault: 'Document controller',
    descDefault: 'Keeps drawings, records and handover in order',
    headgear: 'none',
    badge: FolderOpen,
    avatarText: 'text-slate-600 dark:text-slate-300',
    tint: {
      tile: 'bg-slate-500/10 text-slate-600 ring-slate-500/20 dark:text-slate-300',
      chip: 'border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300',
      accent: 'border-l-slate-400/60',
      text: 'text-slate-600 dark:text-slate-300',
    },
    categories: ['handover', 'quality'],
  },
  {
    id: 'commercial-manager',
    labelKey: 'cases.role.commercial_manager',
    labelDefault: 'Commercial manager',
    descDefault: 'Owns contracts, claims and the bottom line',
    headgear: 'none',
    badge: Handshake,
    avatarText: 'text-green-600 dark:text-green-400',
    tint: {
      tile: 'bg-green-500/10 text-green-600 ring-green-500/20 dark:text-green-400',
      chip: 'border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-300',
      accent: 'border-l-green-400/60',
      text: 'text-green-600 dark:text-green-400',
    },
    categories: ['commercial', 'tendering'],
  },
  {
    id: 'accountant',
    labelKey: 'cases.role.accountant',
    labelDefault: 'Accountant',
    descDefault: 'Books the costs and settles the invoices',
    headgear: 'none',
    badge: Receipt,
    avatarText: 'text-indigo-600 dark:text-indigo-400',
    tint: {
      tile: 'bg-indigo-500/10 text-indigo-600 ring-indigo-500/20 dark:text-indigo-400',
      chip: 'border-indigo-500/40 bg-indigo-500/10 text-indigo-700 dark:text-indigo-300',
      accent: 'border-l-indigo-400/60',
      text: 'text-indigo-600 dark:text-indigo-400',
    },
    categories: ['commercial'],
  },
  {
    id: 'contract-administrator',
    labelKey: 'cases.role.contract_administrator',
    labelDefault: 'Contract administrator',
    descDefault: 'Runs variations, notices and certificates',
    headgear: 'none',
    badge: ScrollText,
    avatarText: 'text-cyan-600 dark:text-cyan-400',
    tint: {
      tile: 'bg-cyan-500/10 text-cyan-600 ring-cyan-500/20 dark:text-cyan-400',
      chip: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
      accent: 'border-l-cyan-400/60',
      text: 'text-cyan-600 dark:text-cyan-400',
    },
    categories: ['commercial', 'tendering'],
  },
  {
    id: 'finance-manager',
    labelKey: 'cases.role.finance_manager',
    labelDefault: 'Finance manager',
    descDefault: 'Watches cash flow, budgets and forecasts',
    headgear: 'none',
    badge: Banknote,
    avatarText: 'text-fuchsia-600 dark:text-fuchsia-400',
    tint: {
      tile: 'bg-fuchsia-500/10 text-fuchsia-600 ring-fuchsia-500/20 dark:text-fuchsia-400',
      chip: 'border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-700 dark:text-fuchsia-300',
      accent: 'border-l-fuchsia-400/60',
      text: 'text-fuchsia-600 dark:text-fuchsia-400',
    },
    categories: ['commercial'],
  },
  {
    id: 'foreman',
    labelKey: 'cases.role.foreman',
    labelDefault: 'Foreman / supervisor',
    descDefault: 'Leads the crew at the workface',
    headgear: 'hardhat',
    badge: Megaphone,
    avatarText: 'text-rose-600 dark:text-rose-400',
    tint: {
      tile: 'bg-rose-500/10 text-rose-600 ring-rose-500/20 dark:text-rose-400',
      chip: 'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300',
      accent: 'border-l-rose-400/60',
      text: 'text-rose-600 dark:text-rose-400',
    },
    categories: ['site'],
  },
];

/** Fast lookup of a role's metadata by id. */
export const ROLE_BY_ID: Record<ProfessionalRole, RoleMeta> = Object.fromEntries(
  ROLE_META.map((r) => [r.id, r]),
) as Record<ProfessionalRole, RoleMeta>;

/** The tint for a role id, falling back to the neutral tint. */
export function tintForRole(role: ProfessionalRole | undefined): CategoryTint {
  return role ? (ROLE_BY_ID[role]?.tint ?? NEUTRAL_TINT) : NEUTRAL_TINT;
}

/**
 * The professional roles a case is relevant to. Uses the case's own `roles`
 * when it sets them; otherwise derives the set from the case discipline and
 * the company types it serves. Always returns at least one role.
 */
export function rolesForPlaybook(pb: Playbook): ProfessionalRole[] {
  if (pb.roles && pb.roles.length > 0) return pb.roles;
  const out = ROLE_META.filter(
    (r) =>
      r.categories.includes(pb.category) ||
      (r.companyTypes?.some((ct) => pb.companyTypes.includes(ct)) ?? false),
  ).map((r) => r.id);
  // Every discipline maps to at least one role, but guard anyway so a future
  // category can never yield an empty (and therefore un-selectable) case.
  return out.length > 0 ? out : ['project-manager'];
}
