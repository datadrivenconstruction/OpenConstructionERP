// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Adding fields and functions to a module that is already installed.
 *
 * The server takes an upgrade only when it is additive: new fields, new links,
 * new checks, new stages and choices, functions switched on, and any change of
 * wording. A changed type, a renamed or removed field, a removed choice, stage,
 * check or function would rewrite records people already keep, so it refuses
 * those. The wizard therefore never offers them: those parts are locked, and
 * the server's refusal stays as the safety net, not as the way a person finds
 * out.
 *
 * What is locked is read off the installed spec, the baseline, by name: a
 * field keeps its name for life, and so does a check its code.
 *
 * A register nobody has recorded anything in yet loses nothing to any change,
 * and the server then takes everything but a new internal name for its
 * entries. So once the preview has said there are no records, the baseline is
 * marked `empty` and only the key and that name stay locked. If entries arrive
 * in the meantime, the server's refusal is the safety net.
 */
import type { ModuleFeatureName, ModuleFieldSpec, ModuleRuleSpec, ModuleSpec } from './api';
import { featuresOf } from './draft';

export interface Baseline {
  spec: ModuleSpec;
  fields: ReadonlySet<string>;
  rules: ReadonlySet<string>;
  /** Functions already on; they stay on. */
  features: ReadonlySet<ModuleFeatureName>;
  /** Nothing is recorded yet: every part may change but the key and the entry's internal name. */
  empty: boolean;
}

const FEATURE_NAMES: readonly ModuleFeatureName[] = ['status', 'due', 'export', 'comments'];

function featuresOn(spec: ModuleSpec): ModuleFeatureName[] {
  const features = featuresOf(spec);
  return FEATURE_NAMES.filter((name) => Boolean(features[name]));
}

export function baselineOf(spec: ModuleSpec): Baseline {
  return {
    spec,
    fields: new Set(spec.entity.fields.map((f) => f.name)),
    rules: new Set(spec.rules.map((r) => r.code.trim().toUpperCase())),
    features: new Set(featuresOn(spec)),
    empty: false,
  };
}

/** The baseline once the server has said how many records the module holds. */
export function withRecordCount(baseline: Baseline, records: number): Baseline {
  const empty = records === 0;
  return empty === baseline.empty ? baseline : { ...baseline, empty };
}

/** True when this field was installed already: its kind and name stay, its wording can change. */
export function isLockedField(baseline: Baseline | null | undefined, field: Pick<ModuleFieldSpec, 'name'>): boolean {
  return Boolean(baseline && !baseline.empty && baseline.fields.has(field.name));
}

export function isLockedRule(baseline: Baseline | null | undefined, rule: Pick<ModuleRuleSpec, 'code'>): boolean {
  return Boolean(baseline && !baseline.empty && baseline.rules.has(rule.code.trim().toUpperCase()));
}

export function isLockedFeature(baseline: Baseline | null | undefined, feature: ModuleFeatureName | undefined): boolean {
  return Boolean(feature && baseline && !baseline.empty && baseline.features.has(feature));
}

/**
 * The installed module as the wizard edits it: what the server handed back,
 * without the stamps it adds on generation, and with the functions filled in.
 */
export function editableFrom(installed: ModuleSpec & { generated_at?: string; generator?: string }): ModuleSpec {
  const { generated_at: _at, generator: _by, ...spec } = installed;
  void _at;
  void _by;
  return { ...spec, features: featuresOf(spec) };
}

export interface Additions {
  fields: ModuleFieldSpec[];
  links: ModuleFieldSpec[];
  rules: ModuleRuleSpec[];
  features: ModuleFeatureName[];
  /** New choices on a field that was already there. */
  choices: { field: string; choice: string }[];
  /** New stages, when stages were already on. */
  stages: string[];
  /** Fields taken away, which only a register with nothing recorded allows. */
  removed: string[];
  /** Names, wording or settings of something already there changed. */
  reworded: boolean;
}

/** Whether the parts already installed read or behave differently, without changing what records hold. */
function rewordedFrom(baseline: Baseline, spec: ModuleSpec): boolean {
  const before = baseline.spec;
  if (
    spec.display_name !== before.display_name ||
    spec.description !== before.description ||
    spec.entity.display_name !== before.entity.display_name ||
    spec.entity.plural_name !== before.entity.plural_name
  ) {
    return true;
  }
  const fields = new Map(spec.entity.fields.map((f) => [f.name, f]));
  for (const was of before.entity.fields) {
    const is = fields.get(was.name);
    if (
      is &&
      (is.label !== was.label ||
        is.help_text !== was.help_text ||
        is.unit !== was.unit ||
        is.in_list !== was.in_list ||
        is.required !== was.required)
    ) {
      return true;
    }
  }
  const rules = new Map(spec.rules.map((r) => [r.code.trim().toUpperCase(), r]));
  for (const was of before.rules) {
    const is = rules.get(was.code.trim().toUpperCase());
    if (is && (is.message !== was.message || is.severity !== was.severity)) return true;
  }
  const states = new Map((featuresOf(spec).status?.states ?? []).map((s) => [s.code, s]));
  for (const was of before.features?.status?.states ?? []) {
    const is = states.get(was.code);
    if (is && (is.label !== was.label || is.done !== was.done)) return true;
  }
  const due = featuresOf(spec).due;
  const dueBefore = before.features?.due;
  return Boolean(
    due && dueBefore && (due.field !== dueBefore.field || due.remind_days_before !== dueBefore.remind_days_before),
  );
}

/** What this upgrade adds, for the "Update module" screen to say in words. */
export function additionsOf(baseline: Baseline, spec: ModuleSpec): Additions {
  const added = spec.entity.fields.filter((f) => !baseline.fields.has(f.name));
  const choices: Additions['choices'] = [];
  for (const was of baseline.spec.entity.fields) {
    const is = spec.entity.fields.find((f) => f.name === was.name);
    if (!is) continue;
    for (const choice of is.options.slice(was.options.length)) {
      if (choice.trim()) choices.push({ field: is.label || is.name, choice });
    }
  }
  const keptStates = new Set((baseline.spec.features?.status?.states ?? []).map((s) => s.code));
  const names = new Set(spec.entity.fields.map((f) => f.name));
  const stages = baseline.features.has('status')
    ? (featuresOf(spec).status?.states ?? []).filter((s) => !keptStates.has(s.code)).map((s) => s.label || s.code)
    : [];
  return {
    fields: added.filter((f) => f.type !== 'link'),
    links: added.filter((f) => f.type === 'link'),
    rules: spec.rules.filter((r) => !baseline.rules.has(r.code.trim().toUpperCase())),
    features: featuresOn(spec).filter((name) => !baseline.features.has(name)),
    choices,
    stages,
    removed: baseline.spec.entity.fields.filter((f) => !names.has(f.name)).map((f) => f.label || f.name),
    // On an empty register anything may have changed, not only the wording.
    reworded: rewordedFrom(baseline, spec) || (baseline.empty && !keepsEverything(baseline.spec, spec)),
  };
}

export function hasAdditions(additions: Additions): boolean {
  return (
    additions.fields.length +
      additions.links.length +
      additions.rules.length +
      additions.features.length +
      additions.choices.length +
      additions.stages.length +
      additions.removed.length >
      0 || additions.reworded
  );
}

/**
 * Whether the spec still holds every installed part exactly as it was.
 *
 * The screens lock all of it, so this is the guard that keeps a slip in some
 * screen from reaching the server as a refused upgrade: the update button
 * stays off while it is false.
 */
export function keepsBaseline(baseline: Baseline, spec: ModuleSpec): boolean {
  const before = baseline.spec;
  if (spec.key !== before.key || spec.entity.name !== before.entity.name) return false;
  return baseline.empty || keepsEverything(before, spec);
}

/** Whether every part entries could hold is still there, as it was. */
function keepsEverything(before: ModuleSpec, spec: ModuleSpec): boolean {
  if (spec.entity.project_scoped !== before.entity.project_scoped) return false;
  const now = new Map(spec.entity.fields.map((f) => [f.name, f]));
  for (const was of before.entity.fields) {
    const is = now.get(was.name);
    if (!is || is.type !== was.type) return false;
    if (was.type === 'link' && is.target !== was.target) return false;
    // A choice entries may hold has to stay, in its place.
    if (was.options.some((option, i) => is.options[i] !== option)) return false;
  }
  const rules = new Map(spec.rules.map((r) => [r.code.trim().toUpperCase(), r]));
  for (const was of before.rules) {
    const is = rules.get(was.code.trim().toUpperCase());
    if (!is) return false;
    if (
      is.kind !== was.kind ||
      is.field !== was.field ||
      is.other_field !== was.other_field ||
      is.min_value !== was.min_value ||
      is.max_value !== was.max_value
    ) {
      return false;
    }
  }
  const on = new Set(featuresOn(spec));
  for (const feature of featuresOn(before)) if (!on.has(feature)) return false;
  const states = new Set((featuresOf(spec).status?.states ?? []).map((s) => s.code));
  for (const state of before.features?.status?.states ?? []) if (!states.has(state.code)) return false;
  return true;
}
