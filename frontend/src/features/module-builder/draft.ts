// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Editing a module specification, and knowing in advance what the server will
 * refuse.
 *
 * The wizard collects a `ModuleSpec` and the server validates it. Sending an
 * unbuildable one and rendering the 422 would work, but it means a person
 * discovers on the last step that a field they named `id` was never going to be
 * allowed. So the checks the spec makes are read here too, before the user
 * moves on.
 *
 * This is a second reader of one rule set rather than a second rule set: every
 * check below exists because `spec.py` refuses that exact thing, and the two
 * agree by both being written from it. The server is still the authority - an
 * install that gets past these can still be refused, and that refusal is shown
 * as it arrives. What this buys is that the ordinary mistakes are answered
 * where they were made.
 *
 * Nothing here mutates: each edit returns a new spec, so the wizard's undo and
 * React's change detection both work without a deep clone at every keystroke.
 */
import type {
  ModuleEntitySpec,
  ModuleFeatures,
  ModuleFieldSpec,
  ModuleFieldType,
  ModuleRuleKind,
  ModuleRuleSpec,
  ModuleSpec,
  Vocabulary,
} from './api';

/** `IDENTIFIER_RE` in spec.py: snake_case, no trailing or doubled underscores. */
export const IDENTIFIER_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/;

/** `_code_shape` in spec.py. */
export const RULE_CODE_RE = /^[A-Z][A-Z0-9_]{2,48}$/;

/** `_version_shape` in spec.py. */
export const VERSION_RE = /^\d+\.\d+\.\d+$/;

/**
 * Python's own keywords, which an identifier may not be.
 *
 * Mirrors `keyword.kwlist` and `keyword.softkwlist`, minus the capitalised ones
 * that a lowercase identifier cannot collide with anyway. A name that gets past
 * this and is added to a later Python is still caught by the server.
 */
export const PYTHON_KEYWORDS = new Set([
  'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def', 'del',
  'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in',
  'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while',
  'with', 'yield', 'case', 'match', 'type', '_',
]);

const NUMERIC_TYPES: ModuleFieldType[] = ['integer', 'number', 'money'];
const TEMPORAL_TYPES: ModuleFieldType[] = ['date', 'datetime'];

/** The spec version the current wizard writes (links and features). */
export const SCHEMA_VERSION = 2;

/** `StatusFeature` bounds in spec.py. */
export const MIN_STATES = 2;
export const MAX_STATES = 8;

/** `DueFeature.remind_days_before` bounds in spec.py. */
export const MAX_REMIND_DAYS = 30;

/** The column the status feature adds; no field may take its name while it is on. */
export const STATUS_FIELD = 'status';

/** Features as a spec with none of them switched on carries them. */
export function noFeatures(): Required<ModuleFeatures> {
  return { status: null, due: null, export: false, comments: false };
}

/** The features of a spec, with the defaults filled in for one written before them. */
export function featuresOf(spec: Pick<ModuleSpec, 'features'>): Required<ModuleFeatures> {
  return { ...noFeatures(), ...(spec.features ?? {}) };
}

/** True when a field of this type can carry a deadline. */
export function isTemporal(type: ModuleFieldType): boolean {
  return TEMPORAL_TYPES.includes(type);
}

/** One thing the server would refuse, said where the user can fix it. */
/**
 * The English of every problem `specProblems` can report, by code.
 *
 * The screen translates `module_builder.problem.<code>` with this as the
 * default, so a problem reads in the person's language; `message` on the
 * problem is this English with the values filled in, for logs and tests.
 */
export const PROBLEM_TEXT = {
  key_needed: 'The register needs an internal name.',
  key_snake: 'This internal name can only use lowercase Latin letters, digits and single underscores, starting with a letter.',
  key_keyword: 'This word is reserved by the system; choose another internal name.',
  key_short: 'This internal name is too short. Use at least three characters.',
  key_shipped: 'A part of the platform is already called {{key}}. Choose another internal name.',
  name_needed: 'The register needs a name people can read.',
  version: 'The version is three numbers separated by dots, such as 1.0.0.',
  entity_needed: 'An entry needs an internal name.',
  entity_snake: 'This internal name can only use lowercase Latin letters, digits and single underscores, starting with a letter.',
  entity_keyword: 'This word is reserved by the system; choose another internal name.',
  entity_label: 'An entry needs a name people can read.',
  no_fields: 'Each entry needs at least one field.',
  too_many_fields: 'An entry can hold at most {{max}} fields.',
  field_needed: 'This field needs an internal name.',
  field_snake: 'This internal name can only use lowercase Latin letters, digits and single underscores, starting with a letter.',
  field_keyword: 'This word is reserved by the system; choose another internal name.',
  field_reserved: 'The system already keeps {{name}} for every entry. Choose another internal name.',
  field_duplicate: 'Two fields have the internal name {{name}}.',
  field_label: 'Every field needs a label. It is what people read.',
  one_option: 'A list of choices needs at least two options.',
  option_twice: 'The same option is listed twice.',
  link_target: 'Choose what {{field}} points at.',
  link_target_unnamed: 'Choose what this field points at.',
  link_off: '{{field}} points at a part of the platform that is switched off here.',
  status_name_taken: 'The stages already use the internal name {{name}}. Choose another one for this field.',
  no_rules: 'Every register checks at least one thing before an entry is saved.',
  rule_code: 'A check code uses capital Latin letters, digits and underscores, 3 to 49 characters, starting with a letter.',
  rule_duplicate: 'Two checks have the code {{code}}.',
  rule_message: 'A check needs a message that tells people what to fix.',
  rule_field_missing: 'This check is about {{field}}, which is no longer a field.',
  rule_no_field: 'Choose the field this check is about.',
  range_bound: 'A range needs a lowest or a highest value.',
  range_order: 'The lowest value is above the highest.',
  not_number: '{{field}} is not a number, so this check cannot apply to it.',
  no_choices: '{{field}} has no list of choices to check against.',
  not_date: '{{field}} is not a date.',
  order_one_field: 'Choose the second date this check compares with.',
  order_self: 'A date cannot be compared with itself.',
  order_dates: 'Only dates can be compared this way.',
  status_count: 'Use between {{min}} and {{max}} stages.',
  state_label: 'Every stage needs a name.',
  state_code: 'A stage\'s internal name can only use lowercase Latin letters, digits and single underscores, starting with a letter.',
  state_duplicate: 'Two stages have the same internal name.',
  due_field: 'Choose the date the reminder counts down to.',
  due_days: 'Reminders go out between 0 and {{max}} days before.',
  due_needs_project: 'Reminders work per project, so the entries have to belong to a project.',
  comments_needs_project: 'Comments work per project, so the entries have to belong to a project.',
} as const;

export type SpecProblemCode = keyof typeof PROBLEM_TEXT;

export type ProblemParams = Record<string, string | number>;

export interface SpecProblem {
  /** `module`, `entity`, `entity:name`, `field:<index>`, `rule:<index>`, `status`, `state:<index>` or `due`. */
  where: string;
  /** Translated as `module_builder.problem.<code>`, with `params`. */
  code: SpecProblemCode;
  params?: ProblemParams;
  /** The English, filled in. */
  message: string;
}

/** A spec with nothing in it yet: one text field and no rules. */
export function emptySpec(): ModuleSpec {
  return {
    key: '',
    display_name: '',
    description: '',
    category: 'community',
    icon: 'Boxes',
    version: '0.1.0',
    author: '',
    entity: {
      name: '',
      display_name: '',
      plural_name: '',
      fields: [newField('text')],
      project_scoped: true,
    },
    rules: [],
    drafted_by: 'wizard',
    schema_version: SCHEMA_VERSION,
    features: noFeatures(),
  };
}

/** A blank field of the given type, with the shape the API expects. */
export function newField(type: ModuleFieldType = 'text'): ModuleFieldSpec {
  return {
    name: '',
    label: '',
    type,
    required: false,
    help_text: '',
    unit: '',
    options: type === 'select' ? ['', ''] : [],
    in_list: true,
  };
}

/**
 * A snake_case identifier from something a person typed.
 *
 * Best effort by design: it is a starting point in an editable box, not a
 * decision. Anything it cannot turn into a legal identifier comes back empty,
 * and the user names it themselves.
 */
export function suggestIdentifier(text: string): string {
  const slug = (text || '')
    .toLowerCase()
    // Keep letters and digits; everything else becomes a separator. Accented
    // letters are stripped rather than transliterated: guessing that "ü" means
    // "ue" is right in German and wrong in Turkish.
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_{2,}/g, '_');
  if (!slug || /^[0-9]/.test(slug)) return '';
  return slug;
}

/** A short, stable tag from any text, so a fallback name is the same on every render. */
function stableTag(text: string): string {
  // FNV-1a: tiny, dependency-free, and enough to tell two names apart.
  let hash = 0x811c9dc5;
  for (const ch of text) {
    hash ^= ch.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(36).slice(0, 5);
}

/**
 * An identifier for something a person named, that the server will accept.
 *
 * `suggestIdentifier` is right for Latin text and returns nothing for a name
 * written in Cyrillic, Greek or Chinese, which would leave a person who never
 * sees identifiers facing a "snake_case" error. So when it has nothing usable
 * this falls back to `<fallback>_<tag>`, the tag derived from the text so it
 * stays put while the person types. Reserved names, Python keywords and names
 * already taken get a numeric suffix rather than an error.
 */
export function autoIdentifier(
  text: string,
  fallback: string,
  taken: Iterable<string> = [],
  minLength = 1,
): string {
  const blocked = new Set(taken);
  let base = suggestIdentifier(text).slice(0, 48).replace(/_+$/, '');
  if (!base || base.length < minLength || !IDENTIFIER_RE.test(base)) {
    const tag = text.trim() ? stableTag(text.trim()) : '';
    base = tag ? `${fallback}_${tag}` : fallback;
  }
  const usable = (name: string) => !blocked.has(name) && !PYTHON_KEYWORDS.has(name);
  if (usable(base)) return base;
  for (let n = 2; n < 1000; n += 1) {
    const candidate = `${base}_${n}`;
    if (usable(candidate)) return candidate;
  }
  return `${base}_${stableTag(base)}`;
}

/** The plural the entity falls back to, matching `_fields_are_distinct` in spec.py. */
export function defaultPlural(displayName: string): string {
  return displayName ? `${displayName}s` : '';
}

/** A rule code from a field name and a kind, e.g. `CREW_SIZE_POSITIVE`. */
export function suggestRuleCode(fieldName: string, kind: ModuleRuleKind): string {
  const base = `${fieldName}_${kind}`.toUpperCase().replace(/[^A-Z0-9_]/g, '_');
  const trimmed = base.replace(/^_+|_+$/g, '').slice(0, 49);
  return RULE_CODE_RE.test(trimmed) ? trimmed : `RULE_${trimmed}`.slice(0, 49);
}

function withEntity(spec: ModuleSpec, entity: Partial<ModuleEntitySpec>): ModuleSpec {
  return { ...spec, entity: { ...spec.entity, ...entity } };
}

export function addField(spec: ModuleSpec, type: ModuleFieldType = 'text'): ModuleSpec {
  return withEntity(spec, { fields: [...spec.entity.fields, newField(type)] });
}

export function updateField(
  spec: ModuleSpec,
  index: number,
  patch: Partial<ModuleFieldSpec>,
): ModuleSpec {
  const fields = spec.entity.fields.map((field, i) => {
    if (i !== index) return field;
    const next = { ...field, ...patch };
    // Changing the type has to bring the options with it, or a field that
    // stopped being a select carries choices the spec then refuses. A patch
    // that says what the options should be wins: it is the caller being
    // explicit, and overriding it would silently discard what they asked for.
    if (patch.type !== undefined && patch.type !== field.type && patch.options === undefined) {
      next.options = patch.type === 'select' ? (field.options.length >= 2 ? field.options : ['', '']) : [];
    }
    // Likewise the link target: only a link carries one, and the server's
    // FieldSpec refuses the key on anything else.
    if (next.type !== 'link') delete next.target;
    else if (next.target === undefined) next.target = null;
    // A field the person retypes by hand is theirs now; there is no earlier
    // column left for a suggestion to hand back.
    if (patch.type !== undefined && patch.type !== field.type) delete next.replaced;
    return next;
  });
  const renamed = patch.name !== undefined && spec.entity.fields[index]?.name !== patch.name;
  if (!renamed) return withEntity(spec, { fields });

  // A rule points at a field by name, and so does the due date. Renaming the
  // field without following them would leave the spec referring to something
  // that no longer exists.
  const before = spec.entity.fields[index]?.name ?? '';
  const after = patch.name ?? '';
  // A field that had no name yet was referred to by nothing: an empty
  // `other_field` means "no second field", not "this one".
  if (before === '') return withEntity(spec, { fields });
  const rules = spec.rules.map((rule) => ({
    ...rule,
    field: rule.field === before ? after : rule.field,
    other_field: rule.other_field === before ? after : rule.other_field,
  }));
  const next: ModuleSpec = { ...withEntity(spec, { fields }), rules };
  const due = spec.features?.due;
  if (due && due.field === before) {
    next.features = { ...featuresOf(spec), due: { ...due, field: after } };
  }
  return next;
}

/** Remove a field, and with it every rule and deadline that could only have been about it. */
export function removeField(spec: ModuleSpec, index: number): ModuleSpec {
  const removed = spec.entity.fields[index];
  if (!removed) return spec;
  const fields = spec.entity.fields.filter((_, i) => i !== index);
  // An unnamed field is what nothing points at; matching on '' would take
  // every rule without a second field with it.
  const rules =
    removed.name === ''
      ? spec.rules
      : spec.rules.filter((rule) => rule.field !== removed.name && rule.other_field !== removed.name);
  const next: ModuleSpec = { ...withEntity(spec, { fields }), rules };
  if (removed.name !== '' && spec.features?.due && spec.features.due.field === removed.name) {
    next.features = { ...featuresOf(spec), due: null };
  }
  return next;
}

/** Switch features on or off. `null` / `false` switches one off. */
export function setFeatures(spec: ModuleSpec, patch: Partial<ModuleFeatures>): ModuleSpec {
  return { ...spec, features: { ...featuresOf(spec), ...patch } };
}

/** Move a field one place up or down. Out-of-range moves are no-ops. */
export function moveField(spec: ModuleSpec, index: number, delta: number): ModuleSpec {
  const target = index + delta;
  const fields = [...spec.entity.fields];
  if (index < 0 || index >= fields.length || target < 0 || target >= fields.length) return spec;
  const moved = fields[index];
  const displaced = fields[target];
  if (!moved || !displaced) return spec;
  fields[index] = displaced;
  fields[target] = moved;
  return withEntity(spec, { fields });
}

export function setOption(spec: ModuleSpec, fieldIndex: number, optionIndex: number, value: string): ModuleSpec {
  const field = spec.entity.fields[fieldIndex];
  if (!field) return spec;
  const options = field.options.map((o, i) => (i === optionIndex ? value : o));
  return updateField(spec, fieldIndex, { options });
}

export function addOption(spec: ModuleSpec, fieldIndex: number): ModuleSpec {
  const field = spec.entity.fields[fieldIndex];
  if (!field) return spec;
  return updateField(spec, fieldIndex, { options: [...field.options, ''] });
}

export function removeOption(spec: ModuleSpec, fieldIndex: number, optionIndex: number): ModuleSpec {
  const field = spec.entity.fields[fieldIndex];
  if (!field) return spec;
  return updateField(spec, fieldIndex, { options: field.options.filter((_, i) => i !== optionIndex) });
}

/**
 * Add a rule. `message` is what a person will be told when it fires; the
 * wizard passes a plain sentence in their language so the rule works the
 * moment it is added, and they can reword it.
 */
export function addRule(spec: ModuleSpec, kind: ModuleRuleKind, fieldName: string, message = ''): ModuleSpec {
  // Two rules of one kind on one field would otherwise share a code, which the
  // server refuses and which nobody on the simple path can even see.
  const taken = new Set(spec.rules.map((r) => r.code.trim().toUpperCase()));
  const base = suggestRuleCode(fieldName || 'rule', kind);
  let code = base;
  for (let n = 2; taken.has(code) && n < 100; n += 1) code = `${base.slice(0, 45)}_${n}`;
  const rule: ModuleRuleSpec = {
    code,
    message,
    kind,
    field: fieldName,
    min_value: null,
    max_value: null,
    other_field: '',
    severity: 'error',
  };
  return { ...spec, rules: [...spec.rules, rule] };
}

export function updateRule(spec: ModuleSpec, index: number, patch: Partial<ModuleRuleSpec>): ModuleSpec {
  return { ...spec, rules: spec.rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)) };
}

export function removeRule(spec: ModuleSpec, index: number): ModuleSpec {
  return { ...spec, rules: spec.rules.filter((_, i) => i !== index) };
}

/** The rule kinds that can be applied to a field of this type. */
export function kindsForType(vocabulary: Vocabulary | undefined, type: ModuleFieldType) {
  if (!vocabulary) return [];
  return vocabulary.rule_kinds.filter((kind) => kind.applies_to.includes(type));
}

function identifierProblem(value: string, what: 'key' | 'entity' | 'field'): SpecProblemCode | null {
  const trimmed = (value || '').trim();
  if (!trimmed) return `${what}_needed`;
  if (!IDENTIFIER_RE.test(trimmed)) return `${what}_snake`;
  if (PYTHON_KEYWORDS.has(trimmed)) return `${what}_keyword`;
  return null;
}

function fillIn(template: string, params?: ProblemParams): string {
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(params?.[name] ?? ''));
}

/**
 * Everything the server would refuse about this spec.
 *
 * An empty list does not promise the install will succeed - the key may have
 * been taken a second ago by someone else, and only the server knows that - but
 * a non-empty one is certain: each entry is a check `spec.py` makes.
 */
export function specProblems(spec: ModuleSpec, vocabulary?: Vocabulary): SpecProblem[] {
  const problems: SpecProblem[] = [];
  const say = (where: string, code: SpecProblemCode, params?: ProblemParams) =>
    problems.push({ where, code, ...(params ? { params } : {}), message: fillIn(PROBLEM_TEXT[code], params) });

  const keyProblem = identifierProblem(spec.key, 'key');
  if (keyProblem) say('module', keyProblem);
  else if (spec.key.trim().length < 3) say('module', 'key_short');
  else if (vocabulary?.reserved_keys.includes(spec.key.trim())) {
    say('module', 'key_shipped', { key: spec.key });
  }

  if (!spec.display_name.trim()) say('module', 'name_needed');
  if (!VERSION_RE.test(spec.version.trim())) say('module', 'version');

  const entityProblem = identifierProblem(spec.entity.name, 'entity');
  if (entityProblem) say('entity:name', entityProblem);
  if (!spec.entity.display_name.trim()) say('entity', 'entity_label');

  const fields = spec.entity.fields;
  if (fields.length === 0) say('entity', 'no_fields');
  if (vocabulary && fields.length > vocabulary.max_fields) {
    say('entity', 'too_many_fields', { max: vocabulary.max_fields });
  }

  const { status, due } = featuresOf(spec);

  const counts = new Map<string, number>();
  for (const field of fields) {
    const name = field.name.trim();
    if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
  }

  fields.forEach((field, index) => {
    const where = `field:${index}`;
    const name = field.name.trim();
    const problem = identifierProblem(name, 'field');
    if (problem) say(where, problem);
    else if (vocabulary?.reserved_field_names.includes(name)) {
      say(where, 'field_reserved', { name });
    } else if ((counts.get(name) ?? 0) > 1) {
      say(where, 'field_duplicate', { name });
    }
    if (!field.label.trim()) say(where, 'field_label');
    if (field.type === 'select') {
      const options = field.options.map((o) => o.trim()).filter(Boolean);
      if (options.length < 2) say(where, 'one_option');
      if (new Set(options).size !== options.length) say(where, 'option_twice');
    }
    const shown = field.label.trim() || name;
    if (field.type === 'link') {
      if (!field.target) {
        if (shown) say(where, 'link_target', { field: shown });
        else say(where, 'link_target_unnamed');
      } else {
        const info = vocabulary?.link_targets?.find((l) => l.target === field.target);
        if (vocabulary?.link_targets && (!info || !info.available)) {
          say(where, 'link_off', { field: shown });
        }
      }
    }
    if (status && name === STATUS_FIELD) {
      say(where, 'status_name_taken', { name: STATUS_FIELD });
    }
  });

  if (spec.rules.length === 0) {
    // Rule 4 of the platform: validation is part of the workflow, not an option.
    say('rules', 'no_rules');
  }

  const byName = new Map(fields.map((f) => [f.name.trim(), f]));
  const ruleCodes = new Map<string, number>();
  for (const rule of spec.rules) {
    const code = rule.code.trim().toUpperCase();
    if (code) ruleCodes.set(code, (ruleCodes.get(code) ?? 0) + 1);
  }

  spec.rules.forEach((rule, index) => {
    const where = `rule:${index}`;
    const code = rule.code.trim().toUpperCase();
    if (!RULE_CODE_RE.test(code)) say(where, 'rule_code');
    else if ((ruleCodes.get(code) ?? 0) > 1) say(where, 'rule_duplicate', { code });
    if (rule.message.trim().length < 4) say(where, 'rule_message');

    const field = byName.get(rule.field.trim());
    if (!field) {
      if (rule.field.trim()) say(where, 'rule_field_missing', { field: rule.field });
      else say(where, 'rule_no_field');
      return;
    }
    const shown = field.label || field.name;
    if (rule.kind === 'range') {
      if (rule.min_value === null && rule.max_value === null) say(where, 'range_bound');
      if (rule.min_value !== null && rule.max_value !== null && rule.min_value > rule.max_value) {
        say(where, 'range_order');
      }
    }
    if ((rule.kind === 'positive' || rule.kind === 'range') && !NUMERIC_TYPES.includes(field.type)) {
      say(where, 'not_number', { field: shown });
    }
    if (rule.kind === 'one_of' && field.type !== 'select') {
      say(where, 'no_choices', { field: shown });
    }
    if (rule.kind === 'not_future' && !TEMPORAL_TYPES.includes(field.type)) {
      say(where, 'not_date', { field: shown });
    }
    if (rule.kind === 'order') {
      const other = byName.get(rule.other_field.trim());
      if (!other) say(where, 'order_one_field');
      else if (rule.other_field.trim() === rule.field.trim()) say(where, 'order_self');
      else if (!TEMPORAL_TYPES.includes(field.type) || !TEMPORAL_TYPES.includes(other.type)) {
        say(where, 'order_dates');
      }
    }
  });

  if (status) {
    const states = status.states;
    if (states.length < MIN_STATES || states.length > MAX_STATES) {
      say('status', 'status_count', { min: MIN_STATES, max: MAX_STATES });
    }
    const codes = states.map((s) => s.code.trim());
    states.forEach((state, index) => {
      if (!state.label.trim()) say(`state:${index}`, 'state_label');
      if (!IDENTIFIER_RE.test(state.code.trim()) || PYTHON_KEYWORDS.has(state.code.trim())) {
        say(`state:${index}`, 'state_code');
      }
    });
    if (new Set(codes).size !== codes.length) say('status', 'state_duplicate');
  }

  if (due) {
    const field = byName.get(due.field.trim());
    if (!field) say('due', 'due_field');
    else if (!TEMPORAL_TYPES.includes(field.type)) say('due', 'not_date', { field: field.label || field.name });
    const days = due.remind_days_before;
    if (!Number.isInteger(days) || days < 0 || days > MAX_REMIND_DAYS) {
      say('due', 'due_days', { max: MAX_REMIND_DAYS });
    }
    if (!spec.entity.project_scoped) say('due', 'due_needs_project');
  }

  // The deadline register and comment access both work per project, and the
  // server refuses either on a register whose entries belong to none.
  if (featuresOf(spec).comments && !spec.entity.project_scoped) {
    say('entity', 'comments_needs_project');
  }

  return problems;
}

/**
 * The spec in the shape this server accepts.
 *
 * A server from before links and features refuses every key it does not know,
 * so for one of those the new keys are left off entirely. For a current server
 * `features` always travels in full and `target` only on a link field, which is
 * the only place spec.py allows it.
 */
export function toWireSpec(spec: ModuleSpec, featuresSupported: boolean): ModuleSpec {
  const fields = spec.entity.fields.map((field) => {
    const { target, replaced: _replaced, ...rest } = field;
    void _replaced;
    return featuresSupported && field.type === 'link' ? { ...rest, target: target ?? null } : rest;
  });
  const { schema_version: _version, features, ...rest } = spec;
  void _version;
  const base: ModuleSpec = { ...rest, entity: { ...spec.entity, fields } };
  if (!featuresSupported) return base;
  return { ...base, schema_version: SCHEMA_VERSION, features: { ...noFeatures(), ...(features ?? {}) } };
}

/**
 * The spec as the API wants it: trimmed, with the plural filled in and the
 * empty select options dropped.
 *
 * The wizard keeps blank options around while a person is typing them; the API
 * refuses a select whose options include an empty string, and it should.
 */
export function normaliseSpec(spec: ModuleSpec): ModuleSpec {
  const displayName = spec.entity.display_name.trim();
  const features = spec.features && {
    ...spec.features,
    status: spec.features.status
      ? {
          states: spec.features.status.states.map((s) => ({
            ...s,
            code: s.code.trim(),
            label: s.label.trim(),
          })),
        }
      : spec.features.status,
    due: spec.features.due ? { ...spec.features.due, field: spec.features.due.field.trim() } : spec.features.due,
  };
  return {
    ...spec,
    ...(features ? { features } : {}),
    key: spec.key.trim(),
    display_name: spec.display_name.trim(),
    description: spec.description.trim(),
    version: spec.version.trim(),
    author: spec.author.trim(),
    entity: {
      ...spec.entity,
      name: spec.entity.name.trim(),
      display_name: displayName,
      plural_name: spec.entity.plural_name.trim() || defaultPlural(displayName),
      fields: spec.entity.fields.map((field) => ({
        ...field,
        name: field.name.trim(),
        label: field.label.trim(),
        help_text: field.help_text.trim(),
        unit: field.unit.trim(),
        options: field.type === 'select' ? field.options.map((o) => o.trim()).filter(Boolean) : [],
      })),
    },
    rules: spec.rules.map((rule) => ({
      ...rule,
      code: rule.code.trim().toUpperCase(),
      message: rule.message.trim(),
      field: rule.field.trim(),
      other_field: rule.kind === 'order' ? rule.other_field.trim() : '',
      min_value: rule.kind === 'range' ? rule.min_value : null,
      max_value: rule.kind === 'range' ? rule.max_value : null,
    })),
  };
}
