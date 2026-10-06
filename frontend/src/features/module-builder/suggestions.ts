// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Applying and withdrawing the builder's suggestions, as pure functions.
 *
 * A suggestion is a proposal and nothing more until a person ticks it (the
 * platform's "AI proposes, human confirms"). The wizard therefore never keeps
 * a separate "accepted" list that could drift from the spec: whether a
 * suggestion is on is read off the spec itself, and ticking or unticking one
 * is a spec edit like any other. That keeps one source of truth, and it means
 * the review token, which binds the spec, binds the accepted suggestions too.
 */
import type { ModuleFieldSpec, ModuleSpec, Suggestion, Vocabulary } from './api';
import { STATUS_FIELD, autoIdentifier, featuresOf, setFeatures } from './draft';

/**
 * Several lists of suggestions as one, first occurrence winning.
 *
 * The caller orders the lists by how specific they are: a template's own hints
 * before the server's general rules, the assistant's draft before both.
 */
export function mergeSuggestions(...lists: Array<readonly Suggestion[] | undefined>): Suggestion[] {
  const seen = new Set<string>();
  const merged: Suggestion[] = [];
  for (const list of lists) {
    for (const suggestion of list ?? []) {
      if (!suggestion || seen.has(suggestion.id)) continue;
      seen.add(suggestion.id);
      merged.push(suggestion);
    }
  }
  return merged;
}

/**
 * The field a link suggestion would take over, or -1 when it adds a new one.
 *
 * The server marks a suggestion that came from one of the person's own columns
 * with `link_field_name`, and names that column in the patch when the column
 * can become the link: a text column labelled "Contract" then turns into the
 * link to a contract instead of sitting beside a second "Contract". When the
 * column cannot be converted (its name would make a database index too long)
 * the patch carries a fresh name instead, and the link goes in beside it.
 * Which of the two happened is decided here, at apply time, and remembered on
 * the field as `replaced`, never guessed again at withdraw.
 */
function replacedFieldIndex(spec: ModuleSpec, suggestion: Suggestion): number {
  if (suggestion.kind !== 'link' || suggestion.reason_code !== 'link_field_name') return -1;
  const name = suggestion.patch.field?.name;
  return spec.entity.fields.findIndex((f) => f.name === name && f.type !== 'link');
}

/** The link field this suggestion added, if the spec still holds one. */
function linkFieldIndex(spec: ModuleSpec, suggestion: Suggestion): number {
  const target = suggestion.target ?? suggestion.patch.field?.target;
  if (!target) return -1;
  return spec.entity.fields.findIndex((f) => f.type === 'link' && f.target === target);
}

/** True when the spec already carries what this suggestion proposes. */
export function isApplied(spec: ModuleSpec, suggestion: Suggestion): boolean {
  if (suggestion.kind === 'link') return linkFieldIndex(spec, suggestion) >= 0;
  const features = featuresOf(spec);
  switch (suggestion.feature) {
    case 'status':
      return features.status !== null && features.status !== undefined;
    case 'due':
      return features.due !== null && features.due !== undefined;
    case 'export':
      return features.export === true;
    case 'comments':
      return features.comments === true;
    default:
      return false;
  }
}

/**
 * Why a suggestion cannot be switched on here.
 *
 * `unavailable`: it points at a part of the platform switched off on this
 * instance, or arrived without what it would change. `full`: the register
 * already holds as many fields as it may. `status_field`: a field is already
 * called `status`, which the status function needs for itself. `needs_project`:
 * reminders and comments work per project, so the server refuses them on a
 * register whose entries do not belong to one.
 */
export type SuggestionBlock = 'unavailable' | 'full' | 'status_field' | 'needs_project';

/** What stops this suggestion from applying, or null when nothing does. */
export function blockedBy(spec: ModuleSpec, suggestion: Suggestion, vocabulary?: Vocabulary): SuggestionBlock | null {
  if (suggestion.kind === 'link') {
    if (!suggestion.patch.field) return 'unavailable';
    const target = suggestion.target ?? suggestion.patch.field.target;
    const info = vocabulary?.link_targets?.find((l) => l.target === target);
    if (vocabulary?.link_targets && (!info || !info.available)) return 'unavailable';
    const replacing = replacedFieldIndex(spec, suggestion) >= 0;
    if (vocabulary && !replacing && spec.entity.fields.length >= vocabulary.max_fields && !isApplied(spec, suggestion)) {
      return 'full';
    }
    return null;
  }
  switch (suggestion.feature) {
    case 'status':
      if (!suggestion.patch.status) return 'unavailable';
      return spec.entity.fields.some((f) => f.name.trim() === STATUS_FIELD) ? 'status_field' : null;
    case 'due':
      if (!suggestion.patch.due) return 'unavailable';
      return spec.entity.project_scoped ? null : 'needs_project';
    case 'comments':
      return spec.entity.project_scoped ? null : 'needs_project';
    case 'export':
      return null;
    default:
      return 'unavailable';
  }
}

/** Whether this suggestion can be applied here at all. */
export function canApply(spec: ModuleSpec, suggestion: Suggestion, vocabulary?: Vocabulary): boolean {
  return blockedBy(spec, suggestion, vocabulary) === null;
}

/** The spec with this suggestion applied. A suggestion that cannot apply leaves it unchanged. */
export function applySuggestion(spec: ModuleSpec, suggestion: Suggestion, vocabulary?: Vocabulary): ModuleSpec {
  if (isApplied(spec, suggestion) || !canApply(spec, suggestion, vocabulary)) return spec;

  if (suggestion.kind === 'link') {
    const proposed = suggestion.patch.field as ModuleFieldSpec;
    const target = suggestion.target ?? proposed.target ?? null;
    const existing = replacedFieldIndex(spec, suggestion);
    if (existing >= 0) {
      // The person's own column becomes the link: their label, list and
      // required choices stay, only what it holds changes.
      const fields = spec.entity.fields.map((f, i) =>
        i === existing ? { ...f, type: 'link' as const, target, options: [], unit: '', replaced: { ...f } } : f,
      );
      return { ...spec, entity: { ...spec.entity, fields } };
    }
    const taken = [
      ...spec.entity.fields.map((f) => f.name),
      ...(vocabulary?.reserved_field_names ?? []),
    ];
    // The proposed name can collide with a field the person already has, for
    // example a free-text "contract" column next to the link to a contract.
    const name = autoIdentifier(proposed.name || proposed.label, 'link', taken);
    const field: ModuleFieldSpec = {
      ...proposed,
      name,
      type: 'link',
      target,
      options: [],
      unit: '',
      help_text: proposed.help_text ?? '',
      in_list: proposed.in_list ?? true,
      required: proposed.required ?? false,
    };
    return { ...spec, entity: { ...spec.entity, fields: [...spec.entity.fields, field] } };
  }

  switch (suggestion.feature) {
    case 'status':
      return setFeatures(spec, {
        status: { states: (suggestion.patch.status?.states ?? []).map((s) => ({ ...s })) },
      });
    case 'due':
      return suggestion.patch.due ? setFeatures(spec, { due: { ...suggestion.patch.due } }) : spec;
    case 'export':
      return setFeatures(spec, { export: true });
    case 'comments':
      return setFeatures(spec, { comments: true });
    default:
      return spec;
  }
}

/**
 * The spec with this suggestion taken back out.
 *
 * A link field goes with every rule that was about it, the same as removing
 * the field by hand, and a deadline that pointed at it goes too. A link that
 * took over one of the person's own columns gives that column back as it was.
 */
export function withdrawSuggestion(spec: ModuleSpec, suggestion: Suggestion): ModuleSpec {
  if (suggestion.kind === 'link') {
    const index = linkFieldIndex(spec, suggestion);
    if (index < 0) return spec;
    const original = spec.entity.fields[index]?.replaced;
    if (original) {
      // Hand the column back as it was, under whatever name it carries now.
      const fields = spec.entity.fields.map((f, i) => (i === index ? { ...original, name: f.name } : f));
      return { ...spec, entity: { ...spec.entity, fields } };
    }
    const removed = spec.entity.fields[index];
    const fields = spec.entity.fields.filter((_, i) => i !== index);
    const rules = spec.rules.filter((r) => r.field !== removed?.name && r.other_field !== removed?.name);
    const next: ModuleSpec = { ...spec, entity: { ...spec.entity, fields }, rules };
    if (removed && spec.features?.due?.field === removed.name) return setFeatures(next, { due: null });
    return next;
  }
  switch (suggestion.feature) {
    case 'status':
      return setFeatures(spec, { status: null });
    case 'due':
      return setFeatures(spec, { due: null });
    case 'export':
      return setFeatures(spec, { export: false });
    case 'comments':
      return setFeatures(spec, { comments: false });
    default:
      return spec;
  }
}

/** Tick or untick one suggestion. */
export function toggleSuggestion(
  spec: ModuleSpec,
  suggestion: Suggestion,
  on: boolean,
  vocabulary?: Vocabulary,
): ModuleSpec {
  return on ? applySuggestion(spec, suggestion, vocabulary) : withdrawSuggestion(spec, suggestion);
}

/** Every applicable suggestion applied, in order. The "accept all" button. */
export function applyAll(spec: ModuleSpec, suggestions: readonly Suggestion[], vocabulary?: Vocabulary): ModuleSpec {
  return suggestions.reduce((acc, s) => applySuggestion(acc, s, vocabulary), spec);
}

/**
 * What the server's rules read from a spec, as one string.
 *
 * Suggestions are asked for again when this changes, so they follow a field
 * the person added in fine-tuning. Link fields and features are left out on
 * purpose: they are what the suggestions add, and asking again because one was
 * accepted would make the proposals shift under the person's cursor.
 */
export function suggestionSignature(spec: ModuleSpec): string {
  return JSON.stringify([
    spec.display_name.trim(),
    spec.description.trim(),
    spec.entity.display_name.trim(),
    spec.entity.fields
      .filter((f) => f.type !== 'link')
      .map((f) => [f.name.trim(), f.type, f.label.trim()]),
  ]);
}
