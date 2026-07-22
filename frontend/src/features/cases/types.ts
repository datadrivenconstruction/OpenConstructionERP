// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases (playbooks) - data model.
//
// A "case" is a cross-module, end-to-end guided scenario. The platform already
// explains each module on its own (Module Guides, the How-it-works hub, the
// journey map); a case is the missing worked example that walks a user THROUGH
// several modules in order, telling them WHAT to do and WHY at each step, with
// a "Go" button that drops them into the real module.
//
// i18n convention: every user-facing string on a Playbook / PlaybookStep is a
// key PLUS an inline English default (the same key + defaultValue pattern used
// by ModuleGuide and the *Guide.ts files). Playbook CONTENT strings live ONLY
// in the data files - they are NEVER added to en.ts. Only the framework chrome
// (page title, runner buttons, labels) is seeded into en.ts. Translators pick
// the inline-default content keys up later.
//
// Internal ref: ddc-lineage:a17f93c4-cases-01

/**
 * One item on the in -> out flow of a step: a short label for a piece of data or
 * an artifact the step consumes (input) or produces (output). Rendered in the
 * stage as chips on either side of the action so the user sees, at a glance,
 * what goes IN to the step and what comes OUT. `label` is the English fallback;
 * pass `labelKey` to localize it (same key + fallback pattern as `moduleLabel`).
 */
export interface StepFlowItem {
  /** Short English label (the fallback). */
  label: string;
  /** Optional i18n key to localize the label. */
  labelKey?: string;
}

/**
 * One step of a playbook: a single thing the user does, in one module.
 *
 * `to` is a real app route and MAY contain a `:projectId` slot
 * (e.g. `/projects/:projectId/boq`). When the user has picked a sample project
 * the slot is filled in; when they have not, the `/projects/:projectId`
 * prefix is stripped so the module opens unscoped (see `resolveStepRoute`).
 *
 * `moduleLabel` is the short module name shown as a chip on the step
 * (e.g. "BOQ"). Pass `moduleLabelKey` to reuse an existing translated
 * sidebar/nav key (e.g. `boq.title`) so the chip is localized for free;
 * when omitted the plain `moduleLabel` renders.
 *
 * `spotlightSelector` is an optional CSS selector reserved for a future
 * in-module highlight (it mirrors ModuleGuide's spotlight contract). It is
 * carried on the model now so data files can declare it without a later
 * schema change.
 */
export interface PlaybookStep {
  /** Stable id, unique within the playbook. Progress is keyed by this, so
   *  do NOT reuse or renumber ids once a case has shipped. */
  id: string;
  /** i18n key for the step title (the short imperative, e.g. "Build the BOQ"). */
  titleKey: string;
  /** Inline English default for the step title. */
  titleDefault: string;
  /** i18n key for the "what you do" copy. */
  whatKey: string;
  /** Inline English default for the "what you do" copy. */
  whatDefault: string;
  /** i18n key for the "why" copy. */
  whyKey: string;
  /** Inline English default for the "why" copy. */
  whyDefault: string;
  /** Short module name shown as a chip on the step (English fallback). */
  moduleLabel: string;
  /** Optional existing nav/title i18n key to localize the module chip. */
  moduleLabelKey?: string;
  /** Target route. May contain a `:projectId` slot for project scoping. */
  to: string;
  /** Optional lucide-react icon name for the step (resolved by the runner). */
  icon?: string;
  /** Optional bespoke process-scene id (see `processScenes.tsx`). When set, the
   *  runner draws a step-specific before -> after process illustration in place
   *  of the generic icon scene, and the case shows its step flow beside the
   *  title. A case opts in step by step; steps without it keep the icon scene. */
  scene?: string;
  /** What this step starts from: the data / artifacts it consumes. Shown as the
   *  "In" side of the in -> out flow on the stage, so the user sees what goes in.
   *  Optional; when omitted the stage shows the action scene without the flow. */
  inputs?: StepFlowItem[];
  /** What this step produces: the data / artifacts it leaves behind. Shown as the
   *  "Out" side of the flow, so the user sees what comes out of the step. */
  outputs?: StepFlowItem[];
  /** Optional one-line sentence shown above the "In" list, explaining in plain
   *  words what the user brings into the step. `inputsHintDefault` is the English
   *  fallback; `inputsHintKey` localizes it (same key + fallback pattern). */
  inputsHintKey?: string;
  inputsHintDefault?: string;
  /** Optional one-line sentence shown above the "Out" list, explaining what the
   *  user walks away with. `outputsHintDefault` is the English fallback. */
  outputsHintKey?: string;
  outputsHintDefault?: string;
  /** Optional CSS selector for a future in-module spotlight highlight. */
  spotlightSelector?: string;
}

/**
 * The construction discipline a case belongs to. Drives the category filter
 * on the Cases hub so a user can narrow the list to the kind of work they do.
 * Keep this list aligned with the chips rendered in `CasesPage`.
 */
export type CaseCategory =
  | 'estimating'
  | 'tendering'
  | 'planning'
  | 'bim'
  | 'site'
  | 'quality'
  | 'commercial'
  | 'handover';

/**
 * The kind of company or role a user works for. This is the PRIMARY
 * organizing axis on the Cases hub: the "I work as..." selector filters the
 * whole list down to the cases actually built for that kind of work. A case
 * almost always fits more than one company type (an estimating case usually
 * serves a general contractor, a subcontractor and a cost consultant at
 * once). Keep this list aligned with `COMPANY_TYPE_META` in
 * `companyTypes.ts`.
 */
export type CompanyType =
  | 'general-contractor'
  | 'subcontractor'
  | 'cost-consultant'
  | 'designer'
  | 'developer-client'
  | 'project-manager'
  | 'bim-consultant'
  | 'owner-operator';

/**
 * The individual professional role a user does day to day, one level finer
 * than `CompanyType` (a "general contractor" employs an estimator, a site
 * manager and a foreman all at once). This is the SECONDARY persona axis on
 * the Cases hub: the "Your role" selector, with an illustrated avatar per
 * role, narrows the list to the cases that person actually runs.
 *
 * A case rarely lists its roles explicitly; when `Playbook.roles` is omitted
 * the relevant roles are derived from the case discipline and company types
 * (see `rolesForPlaybook` in `roles.ts`), so every existing case gets a
 * sensible role set for free. Keep this list aligned with `ROLE_META` in
 * `roles.ts`.
 */
export type ProfessionalRole =
  | 'estimator'
  | 'quantity-surveyor'
  | 'site-manager'
  | 'project-manager'
  | 'bim-coordinator'
  | 'procurement-buyer'
  | 'planner'
  | 'hse-officer'
  | 'design-lead'
  | 'document-controller'
  | 'commercial-manager'
  | 'foreman';

/**
 * The project lifecycle stage a case sits in, ordered from the start of a
 * project to the end. Drives the lifecycle timeline and the sequential case
 * numbering on the Cases hub. When a case does not set `stage` it is derived
 * from the discipline (see `stageForPlaybook` in `stages.ts`). Keep this list
 * aligned with `STAGE_META` in `stages.ts`.
 */
export type LifecycleStage =
  | 'define'
  | 'design'
  | 'estimate'
  | 'procure'
  | 'plan'
  | 'build'
  | 'handover'
  | 'operate';

/**
 * A complete case: an ordered set of steps spanning several modules.
 *
 * Drop a new one into `features/cases/data/<slug>.playbook.ts` as the file's
 * default export; it is auto-discovered (no central registry to edit). `order`
 * controls where the card sits in the list (ascending).
 */
export interface Playbook {
  /** Stable id, unique across all playbooks (matches the file slug). */
  id: string;
  /** Sort order in the case list (ascending). Lower shows first. */
  order: number;
  /** Discipline bucket for the category filter on the Cases hub. */
  category: CaseCategory;
  /** Company types this case is built for (one or more). Drives the primary
   *  "I work as..." selector on the Cases hub; see `companyTypes.ts`. */
  companyTypes: CompanyType[];
  /** Optional explicit professional roles this case is built for. When omitted
   *  the roles are derived from `category` + `companyTypes` (see
   *  `rolesForPlaybook` in `roles.ts`), so most cases never set this. Set it
   *  only when a case is tightly aimed at specific roles the derivation would
   *  miss. */
  roles?: ProfessionalRole[];
  /** Optional explicit project lifecycle stage. When omitted the stage is
   *  derived from `category` (see `stageForPlaybook` in `stages.ts`). Set it
   *  only when the case happens at a different point than its discipline
   *  implies. */
  stage?: LifecycleStage;
  /** Optional explicit ids of the case(s) to run NEXT after this one - its
   *  outputs feed their first step. When omitted the successor is derived from
   *  the in -> out chaining between cases (see `nextCasesFor` in
   *  `relatedness.ts`), so a case is never a dead end. */
  next?: string[];
  /** Optional explicit ids of RELATED cases: siblings that touch the same work
   *  but are not the linear next step. When omitted they are derived from shared
   *  discipline, stage, modules and company types (see `relatedCasesFor`). */
  related?: string[];
  /** i18n key for the case title. */
  titleKey: string;
  /** Inline English default for the case title. */
  titleDefault: string;
  /** i18n key for the one-line case description. */
  descKey: string;
  /** Inline English default for the case description. */
  descDefault: string;
  /** Optional i18n key for a richer, multi-sentence description shown in the
   *  stepper hero under the one-line `desc`. */
  longDescKey?: string;
  /** Inline English default for the richer description. When omitted (with
   *  `longDescKey`) the hero shows only the one-line `desc`. Same key + inline
   *  default pattern as `descKey`/`descDefault`; keep it ASCII-clean. */
  longDescDefault?: string;
  /** Rough time-to-complete in minutes, shown on the card. */
  estMinutes: number;
  /** Optional lucide-react icon name for the case card (resolved by the page). */
  icon?: string;
  /** Ordered steps. At least one is required for the case to be useful. */
  steps: PlaybookStep[];
}

/**
 * Per-run progress for one playbook (optionally scoped to a sample project).
 * Persisted in localStorage by `useCasesStore`, keyed by `runKey`.
 */
export interface PlaybookProgress {
  /** Ids of completed steps. Order is irrelevant; membership is what counts. */
  completedStepIds: string[];
  /** Index of the step the runner is focused on. */
  currentStepIndex: number;
}
