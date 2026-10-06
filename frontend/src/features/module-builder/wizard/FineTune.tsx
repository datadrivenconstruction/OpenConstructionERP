// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Fine-tune": every part of the register, for the person who wants to change
 * it. Collapsed by default, because a template or a draft is already complete
 * and the simple path is to keep pressing the primary button.
 *
 * Inside it the words a person reads (labels, choices, checks, stage names)
 * come first. The identifiers the platform needs (the module key, the table
 * and column names, rule codes, the version) sit one level further down, in
 * "Advanced", filled in automatically from those words. They are visible there
 * because a person may want to read them and because a clash with a module the
 * platform ships is reported against the key, but nobody has to type one.
 *
 * Adding to an installed module (a `baseline` is given), what entries already
 * depend on is locked: a field's kind, link and internal name, its existing
 * choices, a check's kind and bounds, the stages that exist (what counts as
 * finished can change: no stored value does), whether entries
 * belong to a project. Wording stays editable (labels, hints, units, messages,
 * stage names), as do "shown in the table" and "must be filled in", because
 * none of that rewrites a record; the server checks the last one against the
 * entries it holds.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Lock, LockOpen, Plus, Settings2, Table2, Trash2 } from 'lucide-react';
import clsx from 'clsx';

import { Button, Input } from '@/shared/ui';

import type { ModuleFieldType, ModuleRuleKind, ModuleSpec, Vocabulary } from '../api';
import {
  MAX_REMIND_DAYS,
  MAX_STATES,
  STATUS_FIELD,
  addField,
  addOption,
  addRule,
  autoIdentifier,
  defaultPlural,
  featuresOf,
  isTemporal,
  kindsForType,
  moveField,
  removeField,
  removeOption,
  removeRule,
  setFeatures,
  setOption,
  updateField,
  updateRule,
  type SpecProblem,
} from '../draft';
import { TARGET_NAMES, say } from '../copy';
import type { Phrase, Translate } from '../templates';
import { isLockedFeature, isLockedField, isLockedRule, type Baseline } from '../upgrade';
import { Disclosure, ProblemList, SectionHeading } from './shared';

const selectClass =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40';

/** A ready sentence for a new check, so it works the moment it is added. */
const RULE_MESSAGES: Record<ModuleRuleKind, Phrase> = {
  required: { labelKey: 'module_builder.auto_rule.required', defaultLabel: '{{field}} must be filled in.' },
  positive: { labelKey: 'module_builder.auto_rule.positive', defaultLabel: '{{field}} must be above zero.' },
  not_future: { labelKey: 'module_builder.auto_rule.not_future', defaultLabel: '{{field}} cannot be in the future.' },
  range: { labelKey: 'module_builder.auto_rule.range', defaultLabel: '{{field}} is outside the allowed range.' },
  one_of: { labelKey: 'module_builder.auto_rule.one_of', defaultLabel: '{{field}} must be one of the listed choices.' },
  order: { labelKey: 'module_builder.auto_rule.order', defaultLabel: '{{field}} cannot come after the date it is compared with.' },
};

export function autoRuleMessage(t: Translate, kind: ModuleRuleKind, fieldLabel: string): string {
  const phrase = RULE_MESSAGES[kind];
  return t(phrase.labelKey, { field: fieldLabel, defaultValue: phrase.defaultLabel });
}

/** Names a new field may not take: the platform's own, and `status` while the status is on. */
export function reservedNames(spec: ModuleSpec, vocabulary: Vocabulary | undefined): string[] {
  return [...(vocabulary?.reserved_field_names ?? []), ...(featuresOf(spec).status ? [STATUS_FIELD] : [])];
}

/** The mark on a part of an installed module that can no longer change. */
export function LockedMark({ testId }: { testId?: string }) {
  const { t } = useTranslation();
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-surface-secondary px-1.5 py-0.5 text-[11px] font-medium text-content-tertiary"
      title={t('module_builder.locked_hint', {
        defaultValue: 'Entries already use this. Its wording can change. What it holds stays as it is.',
      })}
      data-testid={testId}
    >
      <Lock size={11} aria-hidden />
      {t('module_builder.locked', { defaultValue: 'Already in use' })}
    </span>
  );
}

/** The column name a field would get from its label, avoiding every other field's. */
export function autoFieldName(spec: ModuleSpec, index: number, label: string, vocabulary: Vocabulary | undefined) {
  const others = spec.entity.fields.filter((_, i) => i !== index).map((f) => f.name);
  return autoIdentifier(label, 'field', [...others, ...reservedNames(spec, vocabulary)]);
}

interface FineTuneProps {
  spec: ModuleSpec;
  setSpec: (spec: ModuleSpec) => void;
  vocabulary: Vocabulary | undefined;
  problems: SpecProblem[];
  advancedOpen: boolean;
  setAdvancedOpen: (open: boolean) => void;
  /** Called when the person types a key themselves, so the name stops steering it. */
  onKeyEdited: () => void;
  /** The installed module being added to; its parts are shown locked. */
  baseline?: Baseline | null;
}

export function FineTune({
  spec,
  setSpec,
  vocabulary,
  problems,
  advancedOpen,
  setAdvancedOpen,
  onKeyEdited,
  baseline = null,
}: FineTuneProps) {
  const { t } = useTranslation();
  const features = featuresOf(spec);
  const upgrading = baseline !== null;

  const setEntityDisplayName = (value: string) => {
    const pluralWasSuggested =
      spec.entity.plural_name === '' || spec.entity.plural_name === defaultPlural(spec.entity.display_name);
    setSpec({
      ...spec,
      entity: {
        ...spec.entity,
        display_name: value,
        plural_name: pluralWasSuggested ? defaultPlural(value) : spec.entity.plural_name,
      },
    });
  };

  return (
    <div className="space-y-6" data-testid="module-builder-fine-tune-body">
      {baseline?.empty && (
        <p
          className="flex items-start gap-2 rounded-lg bg-surface-secondary px-3 py-2 text-xs text-content-secondary"
          data-testid="module-builder-upgrade-empty"
        >
          <LockOpen size={13} className="mt-px shrink-0 text-content-tertiary" />
          {t('module_builder.upgrade_empty_intro', {
            defaultValue: 'Nothing is recorded yet, so you can change anything.',
          })}
        </p>
      )}
      {upgrading && !baseline?.empty && (
        <p className="flex items-start gap-2 rounded-lg bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
          <Lock size={13} className="mt-px shrink-0 text-content-tertiary" />
          {t('module_builder.upgrade_locked_intro', {
            defaultValue:
              'What entries already hold stays as it is: the kind of each field, its choices, the checks and the stages. You can rename things and add new fields, choices, stages, checks and functions.',
          })}
        </p>
      )}
      <div className="space-y-3">
        <div>
          <label htmlFor="module-builder-purpose" className="mb-1 block text-sm font-medium text-content-secondary">
            {t('module_builder.purpose_label', { defaultValue: 'What it is for, in one sentence' })}
          </label>
          <textarea
            id="module-builder-purpose"
            value={spec.description}
            rows={2}
            onChange={(e) => setSpec({ ...spec, description: e.target.value })}
            className={clsx(selectClass, 'resize-y')}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            label={t('module_builder.entry_called', { defaultValue: 'One entry is called' })}
            value={spec.entity.display_name}
            onChange={(e) => setEntityDisplayName(e.target.value)}
            data-testid="module-builder-entity-name"
          />
          <Input
            label={t('module_builder.entries_called', { defaultValue: 'Several are called' })}
            value={spec.entity.plural_name}
            onChange={(e) => setSpec({ ...spec, entity: { ...spec.entity, plural_name: e.target.value } })}
          />
        </div>
        <label className="flex items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={spec.entity.project_scoped}
            disabled={upgrading && !baseline?.empty}
            onChange={(e) => setSpec({ ...spec, entity: { ...spec.entity, project_scoped: e.target.checked } })}
            className="mt-0.5 h-4 w-4 rounded border-border-light text-oe-blue focus:ring-oe-blue/40"
          />
          <span>
            <span className="block text-content-primary">
              {t('module_builder.project_scoped', { defaultValue: 'These records belong to a project' })}
            </span>
            <span className="block text-xs text-content-tertiary">
              {t('module_builder.project_scoped_hint', {
                defaultValue: 'Almost everything on a construction project does. Leave it on unless it does not.',
              })}
            </span>
          </span>
        </label>
        <ProblemList problems={problems.filter((p) => p.where === 'entity')} />
      </div>

      <FieldsEditor spec={spec} setSpec={setSpec} vocabulary={vocabulary} problems={problems} baseline={baseline} />
      <RulesEditor spec={spec} setSpec={setSpec} vocabulary={vocabulary} problems={problems} baseline={baseline} />
      {(features.status || features.due) && (
        <FeatureSettings spec={spec} setSpec={setSpec} problems={problems} baseline={baseline} />
      )}

      <Disclosure
        open={advancedOpen}
        onToggle={() => setAdvancedOpen(!advancedOpen)}
        title={t('module_builder.advanced', { defaultValue: 'Advanced' })}
        hint={t('module_builder.advanced_hint', {
          defaultValue: 'Names the platform uses inside. Filled in for you; change them only if you need to.',
        })}
        icon={<Settings2 size={15} />}
        testId="module-builder-advanced"
      >
        <AdvancedSettings
          spec={spec}
          setSpec={setSpec}
          problems={problems}
          onKeyEdited={onKeyEdited}
          baseline={baseline}
        />
      </Disclosure>
    </div>
  );
}

interface EditorProps {
  spec: ModuleSpec;
  setSpec: (spec: ModuleSpec) => void;
  vocabulary: Vocabulary | undefined;
  problems: SpecProblem[];
  baseline?: Baseline | null;
}

/** Roughly how wide a value of this type tends to be, for the placeholder bar. */
const PREVIEW_WIDTH: Partial<Record<ModuleFieldType, string>> = {
  boolean: 'w-6',
  number: 'w-10',
  integer: 'w-10',
  money: 'w-14',
  date: 'w-16',
  datetime: 'w-20',
  select: 'w-14',
  link: 'w-20',
  text: 'w-24',
};

/**
 * The table the module will actually serve, drawn from the fields as they are
 * typed. A register is a thing people recognise by looking at it.
 *
 * The cells are bars, not sample values. Inventing plausible figures here would
 * be the same mistake the insights panel refuses to make: a made-up row reads
 * as if it were a real one, and this is the screen where someone decides
 * whether the module is right. A bar says a value goes here and claims nothing
 * about what it is.
 */
export function TablePreview({ spec }: { spec: ModuleSpec }) {
  const { t } = useTranslation();
  const columns = spec.entity.fields.filter((f) => f.in_list && f.label.trim() !== '');
  const caption = spec.entity.plural_name.trim() || spec.display_name.trim();

  return (
    <div
      className="overflow-hidden rounded-xl border border-border-light bg-surface-secondary/30"
      data-testid="module-builder-preview"
    >
      <div className="flex items-center gap-2 border-b border-border-light bg-surface-primary/60 px-3 py-2">
        <Table2 size={13} className="shrink-0 text-content-tertiary" />
        <p className="min-w-0 truncate text-xs font-medium text-content-secondary">
          {t('module_builder.preview_table', { defaultValue: 'The table this builds' })}
          {caption && <span className="ml-1.5 font-normal text-content-tertiary">{caption}</span>}
        </p>
      </div>
      {columns.length === 0 ? (
        <p className="px-3 py-5 text-center text-xs text-content-tertiary" data-testid="module-builder-preview-empty">
          {t('module_builder.preview_empty', {
            defaultValue: 'No field is shown in the table yet, so the register would open on empty columns.',
          })}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border-light">
                {columns.map((field, i) => (
                  <th key={i} className="whitespace-nowrap px-3 py-1.5 text-xs font-medium text-content-secondary">
                    {field.label}
                    {field.unit.trim() !== '' && (
                      <span className="ml-1 font-normal text-content-quaternary">{field.unit}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[0, 1].map((row) => (
                <tr key={row} className="border-b border-border-light/50 last:border-0">
                  {columns.map((field, i) => (
                    <td key={i} className="px-3 py-2">
                      <span
                        aria-hidden
                        className={clsx('block h-2 rounded-full bg-surface-tertiary', PREVIEW_WIDTH[field.type] ?? 'w-20')}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FieldsEditor({ spec, setSpec, vocabulary, problems, baseline = null }: EditorProps) {
  const { t } = useTranslation();
  const types = vocabulary?.field_types ?? [];
  const atLimit = vocabulary !== undefined && spec.entity.fields.length >= vocabulary.max_fields;
  const targets = (vocabulary?.link_targets ?? []).filter((l) => l.available);

  return (
    <div className="space-y-3">
      <SectionHeading>{t('module_builder.fields_heading', { defaultValue: 'What each entry holds' })}</SectionHeading>
      <TablePreview spec={spec} />

      {spec.entity.fields.map((field, index) => {
        const own = problems.filter((p) => p.where === `field:${index}`);
        // An installed field cannot change at all; a new one cannot move above
        // one, so the installed order stays as it was.
        const locked = isLockedField(baseline, field);
        // Choices entries may already hold stay; new ones can follow them.
        const keptOptions = locked
          ? (baseline?.spec.entity.fields.find((f) => f.name === field.name)?.options.length ?? 0)
          : 0;
        const previousLocked = index > 0 && isLockedField(baseline, spec.entity.fields[index - 1]!);
        return (
          <div
            key={index}
            className={clsx(
              'rounded-xl border p-3 transition-colors focus-within:border-oe-blue/50',
              own.length > 0 ? 'border-semantic-warning/50' : 'border-border-light',
            )}
          >
            {locked && (
              <div className="mb-2">
                <LockedMark testId={`module-builder-field-locked-${index}`} />
              </div>
            )}
            <div className="grid gap-2 sm:grid-cols-12">
              <div className="sm:col-span-5">
                <Input
                  label={t('module_builder.field_label', { defaultValue: 'Label' })}
                  value={field.label}
                  onChange={(e) => {
                    const label = e.target.value;
                    // An installed field keeps its column whatever it is called.
                    const nameWasSuggested =
                      !locked &&
                      (field.name === '' || field.name === autoFieldName(spec, index, field.label, vocabulary));
                    setSpec(
                      updateField(spec, index, {
                        label,
                        ...(nameWasSuggested ? { name: autoFieldName(spec, index, label, vocabulary) } : {}),
                      }),
                    );
                  }}
                  data-testid={`module-builder-field-label-${index}`}
                />
              </div>
              <div className="sm:col-span-4">
                <label className="mb-1 block text-sm font-medium text-content-secondary">
                  {t('module_builder.field_kind', { defaultValue: 'Kind of value' })}
                </label>
                <select
                  value={field.type}
                  disabled={locked}
                  onChange={(e) => setSpec(updateField(spec, index, { type: e.target.value as ModuleFieldType }))}
                  className={selectClass}
                  data-testid={`module-builder-field-type-${index}`}
                >
                  {types.map((type) => (
                    <option key={type.type} value={type.type}>
                      {type.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-3">
                <Input
                  label={t('common.unit', { defaultValue: 'Unit' })}
                  value={field.unit}
                  onChange={(e) => setSpec(updateField(spec, index, { unit: e.target.value }))}
                  disabled={field.type === 'link' || field.type === 'boolean' || field.type === 'select'}
                />
              </div>
            </div>

            {field.type === 'link' && (
              <div className="mt-2">
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  {t('module_builder.link_points_at', { defaultValue: 'Points at' })}
                </label>
                <select
                  value={field.target ?? ''}
                  disabled={locked}
                  onChange={(e) =>
                    setSpec(updateField(spec, index, { target: (e.target.value || null) as typeof field.target }))
                  }
                  className={selectClass}
                  data-testid={`module-builder-field-target-${index}`}
                >
                  <option value="">{t('common.select', { defaultValue: 'Select…' })}</option>
                  {targets.map((l) => (
                    <option key={l.target} value={l.target}>
                      {say(t, TARGET_NAMES[l.target])}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {field.type === 'select' && (
              <div className="mt-2 space-y-1.5" data-testid={`module-builder-field-options-${index}`}>
                <p className="text-xs font-medium text-content-secondary">
                  {t('module_builder.field_options', { defaultValue: 'The choices' })}
                </p>
                {field.options.map((option, optionIndex) => (
                  <div key={optionIndex} className="flex items-center gap-2">
                    <input
                      value={option}
                      disabled={optionIndex < keptOptions}
                      onChange={(e) => setSpec(setOption(spec, index, optionIndex, e.target.value))}
                      aria-label={t('module_builder.field_options', { defaultValue: 'The choices' })}
                      className="min-w-0 flex-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
                    />
                    {optionIndex >= keptOptions && (
                      <button
                        type="button"
                        onClick={() => setSpec(removeOption(spec, index, optionIndex))}
                        aria-label={t('common.remove', { defaultValue: 'Remove' })}
                        className="rounded-md p-1 text-content-tertiary hover:text-semantic-error"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => setSpec(addOption(spec, index))}
                  className="text-xs font-medium text-oe-blue-text hover:text-oe-blue-hover"
                  data-testid={`module-builder-add-option-${index}`}
                >
                  {t('module_builder.add_option', { defaultValue: 'Add a choice' })}
                </button>
              </div>
            )}

            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-4 text-xs text-content-secondary">
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={field.required}
                    onChange={(e) => setSpec(updateField(spec, index, { required: e.target.checked }))}
                    className="h-3.5 w-3.5 rounded border-border-light text-oe-blue"
                    data-testid={`module-builder-field-required-${index}`}
                  />
                  {t('module_builder.field_required', { defaultValue: 'Must be filled in' })}
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={field.in_list}
                    onChange={(e) => setSpec(updateField(spec, index, { in_list: e.target.checked }))}
                    className="h-3.5 w-3.5 rounded border-border-light text-oe-blue"
                    data-testid={`module-builder-field-in-list-${index}`}
                  />
                  {t('module_builder.field_in_list', { defaultValue: 'Show in the table' })}
                </label>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setSpec(moveField(spec, index, -1))}
                  aria-label={t('common.move_up', { defaultValue: 'Move up' })}
                  disabled={index === 0 || locked || previousLocked}
                  className="rounded-md p-1 text-content-tertiary hover:text-content-primary disabled:opacity-30"
                >
                  <ArrowUp size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => setSpec(moveField(spec, index, 1))}
                  aria-label={t('common.move_down', { defaultValue: 'Move down' })}
                  disabled={index === spec.entity.fields.length - 1 || locked}
                  className="rounded-md p-1 text-content-tertiary hover:text-content-primary disabled:opacity-30"
                >
                  <ArrowDown size={13} />
                </button>
                {!locked && (
                  <button
                    type="button"
                    onClick={() => setSpec(removeField(spec, index))}
                    aria-label={t('module_builder.remove_field', { defaultValue: 'Remove this field' })}
                    disabled={spec.entity.fields.length === 1}
                    className="rounded-md p-1 text-content-tertiary hover:text-semantic-error disabled:opacity-30"
                    data-testid={`module-builder-remove-field-${index}`}
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            </div>
            {own.length > 0 && (
              <div className="mt-2">
                <ProblemList problems={own} />
              </div>
            )}
          </div>
        );
      })}

      <div className="flex items-center gap-3">
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus size={13} />}
          disabled={atLimit}
          onClick={() => setSpec(addField(spec))}
          data-testid="module-builder-add-field"
        >
          {t('module_builder.add_field', { defaultValue: 'Add a field' })}
        </Button>
        {/* Two numbers and a slash need no translating, and they turn a dead
            control into a limit the reader saw coming. */}
        {vocabulary !== undefined && (
          <span
            className={clsx(
              'text-xs tabular-nums',
              atLimit ? 'font-medium text-semantic-warning' : 'text-content-quaternary',
            )}
            data-testid="module-builder-field-count"
          >
            {spec.entity.fields.length} / {vocabulary.max_fields}
          </span>
        )}
      </div>
    </div>
  );
}

function RulesEditor({ spec, setSpec, vocabulary, problems, baseline = null }: EditorProps) {
  const { t } = useTranslation();
  const [pendingField, setPendingField] = useState('');
  const named = spec.entity.fields.filter((f) => f.name.trim() !== '');
  const chosen = named.find((f) => f.name === pendingField) ?? named[0];
  const available = chosen ? kindsForType(vocabulary, chosen.type) : [];
  const dateFields = spec.entity.fields.filter((f) => isTemporal(f.type));
  const kindLabel = (kind: string) => vocabulary?.rule_kinds.find((k) => k.kind === kind)?.label ?? kind;
  const fieldLabel = (name: string) => spec.entity.fields.find((f) => f.name === name)?.label || name;
  const own = problems.filter((p) => p.where === 'rules' || p.where.startsWith('rule:'));

  return (
    <div className="space-y-3">
      <SectionHeading>{t('module_builder.checks_heading', { defaultValue: 'What it checks' })}</SectionHeading>
      <p className="text-xs text-content-tertiary">
        {t('module_builder.checks_intro', {
          defaultValue: 'Checks run every time an entry is saved. Every register here has at least one.',
        })}
      </p>

      <div className="flex flex-wrap items-end gap-2 rounded-xl border border-dashed border-border-light p-3">
        <div className="min-w-[10rem] flex-1">
          <label className="mb-1 block text-xs font-medium text-content-secondary">
            {t('module_builder.rule_on_field', { defaultValue: 'About which field' })}
          </label>
          <select
            value={chosen?.name ?? ''}
            onChange={(e) => setPendingField(e.target.value)}
            className={selectClass}
            data-testid="module-builder-rule-field"
          >
            {named.map((field) => (
              <option key={field.name} value={field.name}>
                {field.label || field.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {available.map((kind) => (
            <Button
              key={kind.kind}
              variant="secondary"
              size="sm"
              icon={<Plus size={12} />}
              title={kind.hint}
              onClick={() =>
                setSpec(
                  addRule(
                    spec,
                    kind.kind,
                    chosen?.name ?? '',
                    autoRuleMessage(t, kind.kind, chosen?.label || chosen?.name || ''),
                  ),
                )
              }
              data-testid={`module-builder-add-rule-${kind.kind}`}
            >
              {kind.label}
            </Button>
          ))}
        </div>
      </div>

      {spec.rules.map((rule, index) => {
        const locked = isLockedRule(baseline, rule);
        return (
          <div key={index} className="rounded-xl border border-border-light p-3">
            {locked && (
              <div className="mb-2">
                <LockedMark testId={`module-builder-rule-locked-${index}`} />
              </div>
            )}
            <Input
              label={t('module_builder.rule_message', { defaultValue: 'What the user is told' })}
              value={rule.message}
              onChange={(e) => setSpec(updateRule(spec, index, { message: e.target.value }))}
              data-testid={`module-builder-rule-message-${index}`}
            />

            {rule.kind === 'range' && (
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <Input
                  label={t('module_builder.rule_min', { defaultValue: 'Not below' })}
                  value={rule.min_value === null ? '' : String(rule.min_value)}
                  disabled={locked}
                  inputMode="decimal"
                  onChange={(e) =>
                    setSpec(updateRule(spec, index, { min_value: e.target.value.trim() === '' ? null : Number(e.target.value) }))
                  }
                />
                <Input
                  label={t('module_builder.rule_max', { defaultValue: 'Not above' })}
                  value={rule.max_value === null ? '' : String(rule.max_value)}
                  disabled={locked}
                  inputMode="decimal"
                  onChange={(e) =>
                    setSpec(updateRule(spec, index, { max_value: e.target.value.trim() === '' ? null : Number(e.target.value) }))
                  }
                />
              </div>
            )}

            {rule.kind === 'order' && (
              <div className="mt-2">
                <label className="mb-1 block text-xs font-medium text-content-secondary">
                  {t('module_builder.rule_other_field', { defaultValue: 'Must not come after' })}
                </label>
                <select
                  value={rule.other_field}
                  disabled={locked}
                  onChange={(e) => setSpec(updateRule(spec, index, { other_field: e.target.value }))}
                  className={selectClass}
                >
                  <option value="">{t('common.select', { defaultValue: 'Select…' })}</option>
                  {dateFields
                    .filter((f) => f.name !== rule.field)
                    .map((f) => (
                      <option key={f.name} value={f.name}>
                        {f.label || f.name}
                      </option>
                    ))}
                </select>
              </div>
            )}

            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-content-tertiary">
              <span className="min-w-0 truncate">
                {kindLabel(rule.kind)} · {fieldLabel(rule.field)}
              </span>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={rule.severity === 'warning'}
                    disabled={locked}
                    onChange={(e) => setSpec(updateRule(spec, index, { severity: e.target.checked ? 'warning' : 'error' }))}
                    className="h-3.5 w-3.5 rounded border-border-light text-oe-blue"
                  />
                  {t('module_builder.rule_warning_only', { defaultValue: 'Warn, do not refuse' })}
                </label>
                {!locked && (
                  <button
                    type="button"
                    onClick={() => setSpec(removeRule(spec, index))}
                    aria-label={t('module_builder.remove_rule', { defaultValue: 'Remove this rule' })}
                    className="rounded-md p-1 hover:text-semantic-error"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })}

      <ProblemList problems={own} />
    </div>
  );
}

function FeatureSettings({ spec, setSpec, problems, baseline = null }: Omit<EditorProps, 'vocabulary'>) {
  const { t } = useTranslation();
  const { status, due } = featuresOf(spec);
  const statusLocked = isLockedFeature(baseline, 'status');
  const keptStates = new Set(statusLocked ? (baseline?.spec.features?.status?.states ?? []).map((s) => s.code) : []);
  const dueLocked = isLockedFeature(baseline, 'due');
  const own = problems.filter((p) => p.where === 'status' || p.where === 'due' || p.where.startsWith('state:'));
  const dateFields = spec.entity.fields.filter((f) => isTemporal(f.type) && f.name.trim() !== '');

  return (
    <div className="space-y-4">
      {status && (
        <div className="space-y-2" data-testid="module-builder-states">
          <SectionHeading>{t('module_builder.stages_heading', { defaultValue: 'Stages' })}</SectionHeading>
          {statusLocked && <LockedMark testId="module-builder-states-locked" />}
          {status.states.map((state, index) => (
            <div key={index} className="flex flex-wrap items-center gap-2">
              <input
                value={state.label}
                onChange={(e) =>
                  setSpec(
                    setFeatures(spec, {
                      status: {
                        states: status.states.map((s, i) => (i === index ? { ...s, label: e.target.value } : s)),
                      },
                    }),
                  )
                }
                aria-label={t('module_builder.stage_name', { defaultValue: 'Stage name' })}
                className="min-w-0 flex-1 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-sm text-content-primary"
              />
              <label className="flex items-center gap-1.5 text-xs text-content-secondary">
                <input
                  type="checkbox"
                  checked={state.done}
                  onChange={(e) =>
                    setSpec(
                      setFeatures(spec, {
                        status: {
                          states: status.states.map((s, i) => (i === index ? { ...s, done: e.target.checked } : s)),
                        },
                      }),
                    )
                  }
                  className="h-3.5 w-3.5 rounded border-border-light text-oe-blue"
                />
                {t('module_builder.stage_done', { defaultValue: 'Counts as finished' })}
              </label>
              <button
                type="button"
                disabled={keptStates.has(state.code) || status.states.length <= 2}
                onClick={() =>
                  setSpec(setFeatures(spec, { status: { states: status.states.filter((_, i) => i !== index) } }))
                }
                aria-label={t('common.remove', { defaultValue: 'Remove' })}
                className="rounded-md p-1 text-content-tertiary hover:text-semantic-error disabled:opacity-30"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          {status.states.length < MAX_STATES && (
            <button
              type="button"
              onClick={() =>
                setSpec(
                  setFeatures(spec, {
                    status: {
                      states: [
                        ...status.states,
                        { code: autoIdentifier('', 'stage', status.states.map((s) => s.code)), label: '', done: false },
                      ],
                    },
                  }),
                )
              }
              className="text-xs font-medium text-oe-blue-text hover:text-oe-blue-hover"
            >
              {t('module_builder.add_stage', { defaultValue: 'Add a stage' })}
            </button>
          )}
        </div>
      )}

      {due && (
        <div className="grid gap-3 sm:grid-cols-2" data-testid="module-builder-due">
          {dueLocked && (
            <div className="sm:col-span-2">
              <LockedMark testId="module-builder-due-locked" />
            </div>
          )}
          <div>
            <label className="mb-1 block text-sm font-medium text-content-secondary">
              {t('module_builder.due_field', { defaultValue: 'Remind about this date' })}
            </label>
            <select
              value={due.field}
              onChange={(e) => setSpec(setFeatures(spec, { due: { ...due, field: e.target.value } }))}
              className={selectClass}
            >
              <option value="">{t('common.select', { defaultValue: 'Select…' })}</option>
              {dateFields.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.label || f.name}
                </option>
              ))}
            </select>
          </div>
          <Input
            label={t('module_builder.due_days', { defaultValue: 'Days before' })}
            type="number"
            min={0}
            max={MAX_REMIND_DAYS}
            value={String(due.remind_days_before)}
            onChange={(e) =>
              setSpec(
                setFeatures(spec, {
                  due: { ...due, remind_days_before: e.target.value === '' ? 0 : Math.trunc(Number(e.target.value)) },
                }),
              )
            }
          />
        </div>
      )}

      <ProblemList problems={own} />
    </div>
  );
}

function AdvancedSettings({
  spec,
  setSpec,
  problems,
  onKeyEdited,
  baseline = null,
}: Omit<EditorProps, 'vocabulary'> & { onKeyEdited: () => void }) {
  const { t } = useTranslation();
  const upgrading = baseline !== null;
  const moduleProblems = problems.filter((p) => p.where === 'module');
  const entityProblems = problems.filter((p) => p.where === 'entity:name');

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input
          label={t('module_builder.field_key', { defaultValue: 'Key' })}
          hint={t('module_builder.field_key_hint', {
            defaultValue: 'Used for the folder, the table and the URL. Lower case, underscores.',
          })}
          value={spec.key}
          disabled={upgrading}
          onChange={(e) => {
            onKeyEdited();
            setSpec({ ...spec, key: e.target.value });
          }}
          data-testid="module-builder-key"
        />
        <Input
          label={t('module_builder.field_record_key', { defaultValue: 'Table name' })}
          value={spec.entity.name}
          disabled={upgrading}
          onChange={(e) => setSpec({ ...spec, entity: { ...spec.entity, name: e.target.value } })}
          data-testid="module-builder-table-name"
        />
      </div>
      <ProblemList problems={[...moduleProblems, ...entityProblems]} testId="module-builder-key-problems" />

      <div>
        <p className="mb-1.5 text-sm font-medium text-content-secondary">
          {t('module_builder.column_names', { defaultValue: 'Column names' })}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {spec.entity.fields.map((field, index) => (
            <label key={index} className="flex min-w-0 items-center gap-2 text-xs">
              <span className="w-1/3 min-w-0 truncate text-content-tertiary">{field.label || '—'}</span>
              <input
                value={field.name}
                disabled={isLockedField(baseline, field)}
                onChange={(e) => setSpec(updateField(spec, index, { name: e.target.value }))}
                className="min-w-0 flex-1 rounded-lg border border-border-light bg-surface-primary px-2 py-1 font-mono text-xs text-content-primary"
                data-testid={`module-builder-field-name-${index}`}
              />
            </label>
          ))}
        </div>
      </div>

      {spec.rules.length > 0 && (
        <div>
          <p className="mb-1.5 text-sm font-medium text-content-secondary">
            {t('module_builder.rule_codes', { defaultValue: 'Check codes' })}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {spec.rules.map((rule, index) => (
              <input
                key={index}
                value={rule.code}
                disabled={isLockedRule(baseline, rule)}
                onChange={(e) => setSpec(updateRule(spec, index, { code: e.target.value.toUpperCase() }))}
                aria-label={t('module_builder.rule_code', { defaultValue: 'Code' })}
                className="min-w-0 rounded-lg border border-border-light bg-surface-primary px-2 py-1 font-mono text-xs text-content-primary"
              />
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Input
          label={t('module_builder.field_version', { defaultValue: 'Version' })}
          value={spec.version}
          disabled={upgrading}
          onChange={(e) => setSpec({ ...spec, version: e.target.value })}
        />
        <Input
          label={t('module_builder.field_author', { defaultValue: 'Author' })}
          value={spec.author}
          onChange={(e) => setSpec({ ...spec, author: e.target.value })}
        />
      </div>
    </div>
  );
}
