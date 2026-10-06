// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The wizard's words for things that arrive as codes: link targets, features
 * and the reasons behind a suggestion.
 *
 * Each phrase is a literal `{ labelKey, defaultLabel }` pair on one line, the
 * shape the i18n gates can resolve, rather than a key built from the code at
 * the call site, which no gate can check.
 */
import type { LinkTarget, ModuleFeatureName, Suggestion } from './api';
import type { SuggestionBlock } from './suggestions';
import type { Phrase, Translate } from './templates';

/** What one record of a target is called. */
export const TARGET_NAMES: Record<LinkTarget, Phrase> = {
  contract: { labelKey: 'module_builder.target.contract', defaultLabel: 'Contract' },
  contact: { labelKey: 'module_builder.target.contact', defaultLabel: 'Contact' },
  schedule_activity: { labelKey: 'module_builder.target.schedule_activity', defaultLabel: 'Schedule activity' },
  document: { labelKey: 'module_builder.target.document', defaultLabel: 'Document' },
  user: { labelKey: 'module_builder.target.user', defaultLabel: 'Team member' },
};

/** The headline of a link suggestion. One sentence per target, so each language can inflect it. */
export const LINK_TITLES: Record<LinkTarget, Phrase> = {
  contract: { labelKey: 'module_builder.link_title.contract', defaultLabel: 'Link each entry to a contract' },
  contact: { labelKey: 'module_builder.link_title.contact', defaultLabel: 'Link each entry to a contact' },
  schedule_activity: { labelKey: 'module_builder.link_title.schedule_activity', defaultLabel: 'Link each entry to a schedule activity' },
  document: { labelKey: 'module_builder.link_title.document', defaultLabel: 'Link each entry to a document' },
  user: { labelKey: 'module_builder.link_title.user', defaultLabel: 'Link each entry to a team member' },
};

export const FEATURE_TITLES: Record<ModuleFeatureName, Phrase> = {
  status: { labelKey: 'module_builder.feature.status', defaultLabel: 'Track progress with a status' },
  due: { labelKey: 'module_builder.feature.due', defaultLabel: 'Remind before the due date' },
  export: { labelKey: 'module_builder.feature.export', defaultLabel: 'Export to Excel and CSV' },
  comments: { labelKey: 'module_builder.feature.comments', defaultLabel: 'Discuss entries in comments' },
};

export const FEATURE_DESCRIPTIONS: Record<ModuleFeatureName, Phrase> = {
  status: { labelKey: 'module_builder.feature.status_desc', defaultLabel: 'Each entry moves through stages, shown as a coloured badge you can filter by.' },
  due: { labelKey: 'module_builder.feature.due_desc', defaultLabel: 'A reminder goes out a few days before the date, until the entry is done.' },
  export: { labelKey: 'module_builder.feature.export_desc', defaultLabel: 'One click downloads the list, for sending on or keeping on file.' },
  comments: { labelKey: 'module_builder.feature.comments_desc', defaultLabel: 'The team can talk about an entry right where it is recorded.' },
};

/** Why a suggestion cannot be switched on, in place of its reason. */
export const BLOCK_REASONS: Record<SuggestionBlock, Phrase> = {
  unavailable: { labelKey: 'module_builder.suggestion_unavailable', defaultLabel: 'Not available on this instance.' },
  full: { labelKey: 'module_builder.blocked.full', defaultLabel: 'This register already holds as many fields as it can.' },
  status_field: { labelKey: 'module_builder.blocked.status_field', defaultLabel: 'A field is already called “status”. Rename it in Fine-tune to use stages.' },
  needs_project: { labelKey: 'module_builder.blocked.needs_project', defaultLabel: 'Only for registers whose entries belong to a project. Switch that on in Fine-tune.' },
};

/** Said when a suggestion carries neither a known reason code nor a written reason. */
const GENERIC_REASON: Record<'link' | 'feature', Phrase> = {
  link: { labelKey: 'module_builder.reason.generic_link', defaultLabel: 'Another part of the platform already keeps these records, so there is no need to type them twice.' },
  feature: { labelKey: 'module_builder.reason.generic_feature', defaultLabel: 'Useful for most registers like this one.' },
};

export const say = (t: Translate, phrase: Phrase) => t(phrase.labelKey, { defaultValue: phrase.defaultLabel });

/** The headline of a suggestion card. */
export function suggestionTitle(t: Translate, suggestion: Suggestion): string {
  if (suggestion.kind === 'link') {
    const target = suggestion.target ?? suggestion.patch.field?.target;
    return target ? say(t, LINK_TITLES[target]) : suggestion.patch.field?.label ?? suggestion.id;
  }
  return suggestion.feature ? say(t, FEATURE_TITLES[suggestion.feature]) : suggestion.id;
}

/**
 * One plain sentence on why this was suggested.
 *
 * A reason code is translated here, so the sentence is in the reader's
 * language whoever produced the suggestion. Without one, the assistant's own
 * sentence is shown, which it already wrote in the reader's language. With
 * neither, a generic line rather than nothing, because a toggle with no reason
 * is a toggle a person cannot judge.
 */
export function suggestionReason(t: Translate, suggestion: Suggestion): string {
  const fallback = suggestion.reason?.trim() || say(t, GENERIC_REASON[suggestion.kind]);
  if (!suggestion.reason_code) return fallback;
  return t(`module_builder.reason.${suggestion.reason_code}`, {
    ...(suggestion.reason_params ?? {}),
    defaultValue: fallback,
  });
}
