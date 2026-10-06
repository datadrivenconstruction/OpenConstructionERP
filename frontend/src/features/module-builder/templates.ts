// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Ready-made registers a site team keeps everywhere.
 *
 * A template is a complete, valid specification: fields with sensible types
 * and units, at least one rule, records that belong to a project. It is what
 * makes the path without an AI provider a first-class one, and it is also the
 * fastest path with one: picking "Concrete pours" is quicker than describing
 * it.
 *
 * Two kinds of text live in a template and they are treated differently.
 * Identifiers (the key, field names, rule codes, stage codes) are English
 * snake_case and never change, because they become a table, its columns and a
 * URL. Everything a person reads (the module name, the labels, the choices,
 * the rule messages, the stage names) is an i18n key resolved once, when the
 * template is picked, so a German site engineer gets a German register. From
 * that moment the words are the user's data: they are stored in the spec as
 * written and never translated again, exactly like words the user typed.
 *
 * Every phrase is written as `{ labelKey, defaultLabel }` on one line, the
 * shape the i18n gates resolve, so a missing key is caught before it ships.
 */
import type {
  ModuleFieldSpec,
  ModuleFieldType,
  ModuleRuleKind,
  ModuleRuleSpec,
  ModuleSpec,
  ModuleStateSpec,
  Suggestion,
} from './api';
import { SCHEMA_VERSION, noFeatures } from './draft';

/** A key and the English it renders as. */
export interface Phrase {
  labelKey: string;
  defaultLabel: string;
}

/** The translate function, narrowed to what this file needs. */
export type Translate = (key: string, options?: Record<string, unknown>) => string;

interface TemplateField {
  name: string;
  type: ModuleFieldType;
  label: Phrase;
  required?: boolean;
  unit?: string;
  /** A `select`'s choices: phrases when they are words, plain strings when they are codes like C25/30. */
  options?: Array<Phrase | string>;
  inList?: boolean;
}

interface TemplateRule {
  code: string;
  kind: ModuleRuleKind;
  field: string;
  message: Phrase;
  min?: number;
  max?: number;
  otherField?: string;
}

interface TemplateState {
  code: string;
  label: Phrase;
  done?: boolean;
}

/** Proposals a template makes about itself, merged in front of the server's. */
interface TemplateHints {
  status?: TemplateState[];
  due?: { field: string; days: number };
  export?: boolean;
  comments?: boolean;
}

export interface ModuleTemplate {
  id: string;
  /** A lucide icon name, also stored as the module's icon. */
  icon: string;
  key: string;
  name: Phrase;
  description: Phrase;
  entityName: string;
  entity: Phrase;
  entityPlural: Phrase;
  fields: TemplateField[];
  rules: TemplateRule[];
  hints: TemplateHints;
}

export const MODULE_TEMPLATES: readonly ModuleTemplate[] = [
  {
    id: 'concrete_pours',
    icon: 'Layers',
    key: 'concrete_pours',
    name: { labelKey: 'module_builder.tpl.concrete_pours.name', defaultLabel: 'Concrete pours' },
    description: { labelKey: 'module_builder.tpl.concrete_pours.desc', defaultLabel: 'Every pour on site: where, when, how much, which mix and who signed it off.' },
    entityName: 'pour',
    entity: { labelKey: 'module_builder.tpl.concrete_pours.entity', defaultLabel: 'Pour' },
    entityPlural: { labelKey: 'module_builder.tpl.concrete_pours.entity_plural', defaultLabel: 'Pours' },
    fields: [
      { name: 'reference', type: 'text', required: true, label: { labelKey: 'module_builder.tpl.concrete_pours.f.reference', defaultLabel: 'Pour reference' } },
      { name: 'poured_on', type: 'date', required: true, label: { labelKey: 'module_builder.tpl.concrete_pours.f.poured_on', defaultLabel: 'Poured on' } },
      { name: 'location', type: 'text', label: { labelKey: 'module_builder.tpl.concrete_pours.f.location', defaultLabel: 'Location' } },
      { name: 'volume', type: 'number', unit: 'm3', label: { labelKey: 'module_builder.tpl.concrete_pours.f.volume', defaultLabel: 'Volume' } },
      { name: 'mix', type: 'select', options: ['C20/25', 'C25/30', 'C30/37', 'C35/45'], label: { labelKey: 'module_builder.tpl.concrete_pours.f.mix', defaultLabel: 'Concrete class' } },
      { name: 'slump', type: 'integer', unit: 'mm', inList: false, label: { labelKey: 'module_builder.tpl.concrete_pours.f.slump', defaultLabel: 'Slump' } },
      { name: 'signed_off_by', type: 'text', label: { labelKey: 'module_builder.tpl.concrete_pours.f.signed_off_by', defaultLabel: 'Signed off by' } },
    ],
    rules: [
      { code: 'REFERENCE_REQUIRED', kind: 'required', field: 'reference', message: { labelKey: 'module_builder.tpl.concrete_pours.r.reference', defaultLabel: 'Give the pour a reference so it can be traced.' } },
      { code: 'POURED_ON_NOT_FUTURE', kind: 'not_future', field: 'poured_on', message: { labelKey: 'module_builder.tpl.concrete_pours.r.poured_on', defaultLabel: 'A pour cannot be recorded before it happened.' } },
      { code: 'VOLUME_POSITIVE', kind: 'positive', field: 'volume', message: { labelKey: 'module_builder.tpl.concrete_pours.r.volume', defaultLabel: 'The volume must be above zero.' } },
    ],
    hints: {
      status: [
        { code: 'planned', label: { labelKey: 'module_builder.tpl.concrete_pours.s.planned', defaultLabel: 'Planned' } },
        { code: 'poured', label: { labelKey: 'module_builder.tpl.concrete_pours.s.poured', defaultLabel: 'Poured' } },
        { code: 'approved', done: true, label: { labelKey: 'module_builder.tpl.concrete_pours.s.approved', defaultLabel: 'Approved' } },
      ],
      export: true,
    },
  },
  {
    id: 'work_permits',
    icon: 'FileCheck',
    key: 'work_permits',
    name: { labelKey: 'module_builder.tpl.work_permits.name', defaultLabel: 'Work permits' },
    description: { labelKey: 'module_builder.tpl.work_permits.desc', defaultLabel: 'Permits to work for hot works, heights, confined spaces and more, with their validity.' },
    entityName: 'permit',
    entity: { labelKey: 'module_builder.tpl.work_permits.entity', defaultLabel: 'Permit' },
    entityPlural: { labelKey: 'module_builder.tpl.work_permits.entity_plural', defaultLabel: 'Permits' },
    fields: [
      { name: 'permit_number', type: 'text', required: true, label: { labelKey: 'module_builder.tpl.work_permits.f.permit_number', defaultLabel: 'Permit number' } },
      {
        name: 'permit_kind',
        type: 'select',
        required: true,
        label: { labelKey: 'module_builder.tpl.work_permits.f.permit_kind', defaultLabel: 'Kind of work' },
        options: [
          { labelKey: 'module_builder.tpl.work_permits.o.hot_works', defaultLabel: 'Hot works' },
          { labelKey: 'module_builder.tpl.work_permits.o.height', defaultLabel: 'Work at height' },
          { labelKey: 'module_builder.tpl.work_permits.o.confined', defaultLabel: 'Confined space' },
          { labelKey: 'module_builder.tpl.work_permits.o.excavation', defaultLabel: 'Excavation' },
          { labelKey: 'module_builder.tpl.work_permits.o.electrical', defaultLabel: 'Electrical isolation' },
        ],
      },
      { name: 'valid_from', type: 'date', required: true, label: { labelKey: 'module_builder.tpl.work_permits.f.valid_from', defaultLabel: 'Valid from' } },
      { name: 'valid_until', type: 'date', required: true, label: { labelKey: 'module_builder.tpl.work_permits.f.valid_until', defaultLabel: 'Valid until' } },
      { name: 'issued_to', type: 'text', label: { labelKey: 'module_builder.tpl.work_permits.f.issued_to', defaultLabel: 'Issued to' } },
      { name: 'issued_by', type: 'text', label: { labelKey: 'module_builder.tpl.work_permits.f.issued_by', defaultLabel: 'Issued by' } },
      { name: 'conditions', type: 'long_text', inList: false, label: { labelKey: 'module_builder.tpl.work_permits.f.conditions', defaultLabel: 'Conditions and precautions' } },
    ],
    rules: [
      { code: 'PERMIT_NUMBER_REQUIRED', kind: 'required', field: 'permit_number', message: { labelKey: 'module_builder.tpl.work_permits.r.permit_number', defaultLabel: 'A permit needs its number.' } },
      { code: 'VALID_FROM_BEFORE_UNTIL', kind: 'order', field: 'valid_from', otherField: 'valid_until', message: { labelKey: 'module_builder.tpl.work_permits.r.validity', defaultLabel: 'A permit cannot end before it starts.' } },
    ],
    hints: {
      status: [
        { code: 'requested', label: { labelKey: 'module_builder.tpl.work_permits.s.requested', defaultLabel: 'Requested' } },
        { code: 'approved', label: { labelKey: 'module_builder.tpl.work_permits.s.approved', defaultLabel: 'Approved' } },
        { code: 'closed', done: true, label: { labelKey: 'module_builder.tpl.work_permits.s.closed', defaultLabel: 'Closed' } },
        { code: 'rejected', done: true, label: { labelKey: 'module_builder.tpl.work_permits.s.rejected', defaultLabel: 'Rejected' } },
      ],
      due: { field: 'valid_until', days: 1 },
      comments: true,
    },
  },
  {
    id: 'site_measurements',
    icon: 'Ruler',
    key: 'site_measurements',
    name: { labelKey: 'module_builder.tpl.site_measurements.name', defaultLabel: 'Site measurements' },
    description: { labelKey: 'module_builder.tpl.site_measurements.desc', defaultLabel: 'Quantities measured on site, where and by whom, ready to agree with the client.' },
    entityName: 'measurement',
    entity: { labelKey: 'module_builder.tpl.site_measurements.entity', defaultLabel: 'Measurement' },
    entityPlural: { labelKey: 'module_builder.tpl.site_measurements.entity_plural', defaultLabel: 'Measurements' },
    fields: [
      { name: 'item', type: 'text', required: true, label: { labelKey: 'module_builder.tpl.site_measurements.f.item', defaultLabel: 'What was measured' } },
      { name: 'measured_on', type: 'date', required: true, label: { labelKey: 'module_builder.tpl.site_measurements.f.measured_on', defaultLabel: 'Measured on' } },
      { name: 'location', type: 'text', label: { labelKey: 'module_builder.tpl.site_measurements.f.location', defaultLabel: 'Location' } },
      { name: 'quantity', type: 'number', required: true, label: { labelKey: 'module_builder.tpl.site_measurements.f.quantity', defaultLabel: 'Quantity' } },
      { name: 'unit_of_measure', type: 'select', options: ['m', 'm2', 'm3', 't', 'kg', 'pcs'], label: { labelKey: 'module_builder.tpl.site_measurements.f.unit_of_measure', defaultLabel: 'Unit' } },
      { name: 'measured_by', type: 'text', label: { labelKey: 'module_builder.tpl.site_measurements.f.measured_by', defaultLabel: 'Measured by' } },
      { name: 'notes', type: 'long_text', inList: false, label: { labelKey: 'module_builder.tpl.site_measurements.f.notes', defaultLabel: 'Notes' } },
    ],
    rules: [
      { code: 'QUANTITY_POSITIVE', kind: 'positive', field: 'quantity', message: { labelKey: 'module_builder.tpl.site_measurements.r.quantity', defaultLabel: 'A measured quantity must be above zero.' } },
      { code: 'MEASURED_ON_NOT_FUTURE', kind: 'not_future', field: 'measured_on', message: { labelKey: 'module_builder.tpl.site_measurements.r.measured_on', defaultLabel: 'A measurement cannot be dated in the future.' } },
    ],
    hints: {
      status: [
        { code: 'draft', label: { labelKey: 'module_builder.tpl.site_measurements.s.draft', defaultLabel: 'Draft' } },
        { code: 'checked', label: { labelKey: 'module_builder.tpl.site_measurements.s.checked', defaultLabel: 'Checked' } },
        { code: 'agreed', done: true, label: { labelKey: 'module_builder.tpl.site_measurements.s.agreed', defaultLabel: 'Agreed' } },
      ],
      export: true,
    },
  },
  {
    id: 'material_deliveries',
    icon: 'Truck',
    key: 'material_deliveries',
    name: { labelKey: 'module_builder.tpl.material_deliveries.name', defaultLabel: 'Material deliveries' },
    description: { labelKey: 'module_builder.tpl.material_deliveries.desc', defaultLabel: 'What arrived on site, from whom, how much, and in what condition.' },
    entityName: 'delivery',
    entity: { labelKey: 'module_builder.tpl.material_deliveries.entity', defaultLabel: 'Delivery' },
    entityPlural: { labelKey: 'module_builder.tpl.material_deliveries.entity_plural', defaultLabel: 'Deliveries' },
    fields: [
      { name: 'delivery_note', type: 'text', required: true, label: { labelKey: 'module_builder.tpl.material_deliveries.f.delivery_note', defaultLabel: 'Delivery note number' } },
      { name: 'delivered_on', type: 'date', required: true, label: { labelKey: 'module_builder.tpl.material_deliveries.f.delivered_on', defaultLabel: 'Delivered on' } },
      { name: 'supplier', type: 'text', required: true, label: { labelKey: 'module_builder.tpl.material_deliveries.f.supplier', defaultLabel: 'Supplier' } },
      { name: 'material', type: 'text', required: true, label: { labelKey: 'module_builder.tpl.material_deliveries.f.material', defaultLabel: 'Material' } },
      { name: 'quantity', type: 'number', label: { labelKey: 'module_builder.tpl.material_deliveries.f.quantity', defaultLabel: 'Quantity' } },
      { name: 'unit_of_measure', type: 'select', options: ['pcs', 'm', 'm2', 'm3', 't', 'kg'], label: { labelKey: 'module_builder.tpl.material_deliveries.f.unit_of_measure', defaultLabel: 'Unit' } },
      {
        name: 'condition',
        type: 'select',
        label: { labelKey: 'module_builder.tpl.material_deliveries.f.condition', defaultLabel: 'Condition' },
        options: [
          { labelKey: 'module_builder.tpl.material_deliveries.o.complete', defaultLabel: 'Complete and undamaged' },
          { labelKey: 'module_builder.tpl.material_deliveries.o.partial', defaultLabel: 'Partial delivery' },
          { labelKey: 'module_builder.tpl.material_deliveries.o.damaged', defaultLabel: 'Damaged' },
        ],
      },
      { name: 'received_by', type: 'text', label: { labelKey: 'module_builder.tpl.material_deliveries.f.received_by', defaultLabel: 'Received by' } },
    ],
    rules: [
      { code: 'QUANTITY_POSITIVE', kind: 'positive', field: 'quantity', message: { labelKey: 'module_builder.tpl.material_deliveries.r.quantity', defaultLabel: 'The delivered quantity must be above zero.' } },
      { code: 'DELIVERED_ON_NOT_FUTURE', kind: 'not_future', field: 'delivered_on', message: { labelKey: 'module_builder.tpl.material_deliveries.r.delivered_on', defaultLabel: 'A delivery cannot be recorded before it arrived.' } },
    ],
    hints: {
      status: [
        { code: 'expected', label: { labelKey: 'module_builder.tpl.material_deliveries.s.expected', defaultLabel: 'Expected' } },
        { code: 'received', done: true, label: { labelKey: 'module_builder.tpl.material_deliveries.s.received', defaultLabel: 'Received' } },
        { code: 'returned', done: true, label: { labelKey: 'module_builder.tpl.material_deliveries.s.returned', defaultLabel: 'Returned' } },
      ],
      export: true,
    },
  },
  {
    id: 'site_diary',
    icon: 'CloudSun',
    key: 'site_weather_diary',
    name: { labelKey: 'module_builder.tpl.site_diary.name', defaultLabel: 'Site diary with weather' },
    description: { labelKey: 'module_builder.tpl.site_diary.desc', defaultLabel: 'One entry per day: the weather, who was on site, what got done and what held it up.' },
    entityName: 'diary_entry',
    entity: { labelKey: 'module_builder.tpl.site_diary.entity', defaultLabel: 'Diary entry' },
    entityPlural: { labelKey: 'module_builder.tpl.site_diary.entity_plural', defaultLabel: 'Diary entries' },
    fields: [
      { name: 'entry_date', type: 'date', required: true, label: { labelKey: 'module_builder.tpl.site_diary.f.entry_date', defaultLabel: 'Date' } },
      {
        name: 'weather',
        type: 'select',
        label: { labelKey: 'module_builder.tpl.site_diary.f.weather', defaultLabel: 'Weather' },
        options: [
          { labelKey: 'module_builder.tpl.site_diary.o.sunny', defaultLabel: 'Sunny' },
          { labelKey: 'module_builder.tpl.site_diary.o.cloudy', defaultLabel: 'Cloudy' },
          { labelKey: 'module_builder.tpl.site_diary.o.rain', defaultLabel: 'Rain' },
          { labelKey: 'module_builder.tpl.site_diary.o.snow', defaultLabel: 'Snow' },
          { labelKey: 'module_builder.tpl.site_diary.o.storm', defaultLabel: 'Storm' },
        ],
      },
      { name: 'temperature_low', type: 'number', unit: '°C', label: { labelKey: 'module_builder.tpl.site_diary.f.temperature_low', defaultLabel: 'Lowest temperature' } },
      { name: 'temperature_high', type: 'number', unit: '°C', label: { labelKey: 'module_builder.tpl.site_diary.f.temperature_high', defaultLabel: 'Highest temperature' } },
      { name: 'workers_on_site', type: 'integer', label: { labelKey: 'module_builder.tpl.site_diary.f.workers_on_site', defaultLabel: 'People on site' } },
      { name: 'work_done', type: 'long_text', label: { labelKey: 'module_builder.tpl.site_diary.f.work_done', defaultLabel: 'Work done' } },
      { name: 'delays', type: 'long_text', inList: false, label: { labelKey: 'module_builder.tpl.site_diary.f.delays', defaultLabel: 'Delays and their causes' } },
    ],
    rules: [
      { code: 'ENTRY_DATE_NOT_FUTURE', kind: 'not_future', field: 'entry_date', message: { labelKey: 'module_builder.tpl.site_diary.r.entry_date', defaultLabel: 'A diary entry cannot be written for a day that has not come yet.' } },
      { code: 'TEMPERATURE_HIGH_RANGE', kind: 'range', field: 'temperature_high', min: -60, max: 60, message: { labelKey: 'module_builder.tpl.site_diary.r.temperature', defaultLabel: 'That temperature looks like a typing mistake.' } },
      { code: 'WORKERS_ON_SITE_RANGE', kind: 'range', field: 'workers_on_site', min: 0, max: 5000, message: { labelKey: 'module_builder.tpl.site_diary.r.workers', defaultLabel: 'The number of people on site cannot be negative.' } },
    ],
    hints: { comments: true, export: true },
  },
  {
    id: 'safety_briefings',
    icon: 'HardHat',
    key: 'safety_briefings',
    name: { labelKey: 'module_builder.tpl.safety_briefings.name', defaultLabel: 'Safety briefings' },
    description: { labelKey: 'module_builder.tpl.safety_briefings.desc', defaultLabel: 'Toolbox talks and inductions: the topic, who gave it and how many attended.' },
    entityName: 'briefing',
    entity: { labelKey: 'module_builder.tpl.safety_briefings.entity', defaultLabel: 'Briefing' },
    entityPlural: { labelKey: 'module_builder.tpl.safety_briefings.entity_plural', defaultLabel: 'Briefings' },
    fields: [
      { name: 'held_on', type: 'date', required: true, label: { labelKey: 'module_builder.tpl.safety_briefings.f.held_on', defaultLabel: 'Held on' } },
      { name: 'topic', type: 'text', required: true, label: { labelKey: 'module_builder.tpl.safety_briefings.f.topic', defaultLabel: 'Topic' } },
      {
        name: 'briefing_kind',
        type: 'select',
        label: { labelKey: 'module_builder.tpl.safety_briefings.f.briefing_kind', defaultLabel: 'Kind of briefing' },
        options: [
          { labelKey: 'module_builder.tpl.safety_briefings.o.induction', defaultLabel: 'Site induction' },
          { labelKey: 'module_builder.tpl.safety_briefings.o.toolbox', defaultLabel: 'Toolbox talk' },
          { labelKey: 'module_builder.tpl.safety_briefings.o.task', defaultLabel: 'Task briefing' },
        ],
      },
      { name: 'given_by', type: 'text', required: true, label: { labelKey: 'module_builder.tpl.safety_briefings.f.given_by', defaultLabel: 'Given by' } },
      { name: 'attendees', type: 'integer', label: { labelKey: 'module_builder.tpl.safety_briefings.f.attendees', defaultLabel: 'Attendees' } },
      { name: 'duration_minutes', type: 'integer', unit: 'min', label: { labelKey: 'module_builder.tpl.safety_briefings.f.duration_minutes', defaultLabel: 'Duration' } },
      { name: 'notes', type: 'long_text', inList: false, label: { labelKey: 'module_builder.tpl.safety_briefings.f.notes', defaultLabel: 'Notes' } },
    ],
    rules: [
      { code: 'HELD_ON_NOT_FUTURE', kind: 'not_future', field: 'held_on', message: { labelKey: 'module_builder.tpl.safety_briefings.r.held_on', defaultLabel: 'A briefing cannot be recorded before it was held.' } },
      { code: 'ATTENDEES_POSITIVE', kind: 'positive', field: 'attendees', message: { labelKey: 'module_builder.tpl.safety_briefings.r.attendees', defaultLabel: 'A briefing needs at least one attendee.' } },
    ],
    hints: { export: true, comments: true },
  },
];

/** Every phrase a template uses, for the test that holds en.ts to them. */
export function templatePhrases(template: ModuleTemplate): Phrase[] {
  const phrases: Phrase[] = [template.name, template.description, template.entity, template.entityPlural];
  for (const field of template.fields) {
    phrases.push(field.label);
    for (const option of field.options ?? []) if (typeof option !== 'string') phrases.push(option);
  }
  for (const rule of template.rules) phrases.push(rule.message);
  for (const state of template.hints.status ?? []) phrases.push(state.label);
  return phrases;
}

const say = (t: Translate, phrase: Phrase) => t(phrase.labelKey, { defaultValue: phrase.defaultLabel });

/**
 * The template as a specification, in the reader's language.
 *
 * `takenKeys` are the keys of modules already installed here: a second
 * "Concrete pours" becomes `concrete_pours_2` rather than a refusal at install
 * that names a key the person never saw.
 */
export function buildFromTemplate(
  template: ModuleTemplate,
  t: Translate,
  takenKeys: Iterable<string> = [],
): ModuleSpec {
  const taken = new Set(takenKeys);
  let key = template.key;
  for (let n = 2; taken.has(key) && n < 100; n += 1) key = `${template.key}_${n}`;

  const fields: ModuleFieldSpec[] = template.fields.map((field) => ({
    name: field.name,
    label: say(t, field.label),
    type: field.type,
    required: field.required ?? false,
    help_text: '',
    unit: field.unit ?? '',
    options: (field.options ?? []).map((o) => (typeof o === 'string' ? o : say(t, o))),
    in_list: field.inList ?? true,
  }));

  const rules: ModuleRuleSpec[] = template.rules.map((rule) => ({
    code: rule.code,
    message: say(t, rule.message),
    kind: rule.kind,
    field: rule.field,
    min_value: rule.min ?? null,
    max_value: rule.max ?? null,
    other_field: rule.otherField ?? '',
    severity: 'error',
  }));

  return {
    key,
    display_name: say(t, template.name),
    description: say(t, template.description),
    category: 'community',
    icon: template.icon,
    version: '0.1.0',
    author: '',
    entity: {
      name: template.entityName,
      display_name: say(t, template.entity),
      plural_name: say(t, template.entityPlural),
      fields,
      project_scoped: true,
    },
    rules,
    drafted_by: 'wizard',
    schema_version: SCHEMA_VERSION,
    features: noFeatures(),
  };
}

/**
 * The template's own proposals, in the shape the server's come in.
 *
 * They lead the merged list because they know the register: a work permit's
 * stages are not the generic open, in progress and done. None of them is
 * applied: like every suggestion, they wait for a tick.
 */
export function templateSuggestions(template: ModuleTemplate, t: Translate): Suggestion[] {
  const out: Suggestion[] = [];
  const { hints } = template;
  if (hints.status) {
    const states: ModuleStateSpec[] = hints.status.map((s) => ({
      code: s.code,
      label: say(t, s.label),
      done: s.done ?? false,
    }));
    out.push({
      id: 'feature:status',
      kind: 'feature',
      feature: 'status',
      confidence: 'high',
      reason_code: 'status_register',
      patch: { status: { states } },
    });
  }
  if (hints.due) {
    const field = template.fields.find((f) => f.name === hints.due?.field);
    out.push({
      id: 'feature:due',
      kind: 'feature',
      feature: 'due',
      confidence: 'high',
      reason_code: 'due_date_field',
      reason_params: { field: field ? say(t, field.label) : hints.due.field },
      patch: { due: { field: hints.due.field, remind_days_before: hints.due.days } },
    });
  }
  if (hints.export) {
    out.push({
      id: 'feature:export',
      kind: 'feature',
      feature: 'export',
      confidence: 'medium',
      reason_code: 'export_register',
      patch: { export: true },
    });
  }
  if (hints.comments) {
    out.push({
      id: 'feature:comments',
      kind: 'feature',
      feature: 'comments',
      confidence: 'medium',
      reason_code: 'comments_register',
      patch: { comments: true },
    });
  }
  return out;
}

export function findTemplate(id: string): ModuleTemplate | undefined {
  return MODULE_TEMPLATES.find((tpl) => tpl.id === id);
}
