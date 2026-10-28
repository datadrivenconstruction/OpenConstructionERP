// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The standards the project builds to and the quality requirements that
// follow from them. A requirement written here is stored in the project's
// requirement set, so it is the same record the requirements module shows.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';

import {
  addRequirement,
  createStandard,
  deleteStandard,
  patchStandard,
  type AppliedStandard,
  type Mandate,
} from './api';
import { useQcWrite, useRequirements, useStandards } from './hooks';
import { ClosedReasons, SharedReasons } from './ClosedReasons';
import { planRowActions, sharedReasons } from './rules';
import { MANDATE, VERIFICATION_METHOD, catalogueName, gate, nameIn, vocab, type TFn } from './labels';
import type { PanelProps } from './panel';
import { Field, FormDialog, Hint, RefusalNote, Section, VocabSelect, inputCls } from './QualityBits';

const MANDATES = ['statute', 'contract', 'voluntary'] as const;
const METHODS = ['inspection', 'analysis', 'demonstration', 'test', 'document_review', 'model_check'] as const;

export function StandardsSection(props: PanelProps) {
  const { projectId, catalogue, labels, editable, manage } = props;
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const standards = useStandards(projectId);
  const requirements = useRequirements(projectId);
  const [editing, setEditing] = useState<AppliedStandard | 'new' | null>(null);
  const [removing, setRemoving] = useState<AppliedStandard | null>(null);
  const [addingRequirement, setAddingRequirement] = useState(false);

  return (
    <>
      <Section
        testId="standards-section"
        title={t('qualityConcept.standards.title', { defaultValue: 'Standards basis' })}
        description={t('qualityConcept.standards.body', {
          defaultValue: 'The standards the works are built and tested to, with the edition that applies.',
        })}
        action={
          <Button size="sm" variant="secondary" icon={<Plus size={14} />} disabled={!editable} onClick={() => setEditing('new')} data-testid="standard-add">
            {t('qualityConcept.standards.add', { defaultValue: 'Add standard' })}
          </Button>
        }
      >
        <RefusalNote refusal={write.refusal} />
        {(standards.data ?? []).length === 0 ? (
          <Hint testId="standards-empty">
            {t('qualityConcept.standards.empty', {
              defaultValue: 'No standard yet. Name at least one: the concept cannot be submitted without a standards basis.',
            })}
          </Hint>
        ) : (
          <ul className="divide-y divide-border-light" data-testid="standards-list">
            {sharedReasons(standards.data ?? [], planRowActions).length > 0 && (
              <li>
                <SharedReasons codes={sharedReasons(standards.data ?? [], planRowActions)} />
              </li>
            )}
            {(standards.data ?? []).map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2 py-2 text-sm" data-testid="standard-entry">
                <span className="font-medium text-content-primary">{s.code}</span>
                {s.edition && <span className="text-content-tertiary">{s.edition}</span>}
                <span className="min-w-0 flex-1 text-content-secondary">{s.title}</span>
                {s.family_code && (
                  <span className="text-xs text-content-tertiary">{nameIn(labels, catalogue?.standard_families, s.family_code)}</span>
                )}
                <span className="text-xs text-content-tertiary">{vocab(t as TFn, MANDATE, s.mandate)}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  {...gate(t as TFn, s, 'edit', editable)}
                  icon={<Pencil size={14} />}
                  aria-label={t('qualityConcept.common.edit', { defaultValue: 'Edit' })}
                  onClick={() => setEditing(s)}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  {...gate(t as TFn, s, 'delete', editable)}
                  icon={<Trash2 size={14} />}
                  aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
                  onClick={() => setRemoving(s)}
                />
                <ClosedReasons row={s} actions={planRowActions()} skip={sharedReasons(standards.data ?? [], planRowActions)} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        testId="requirements-section"
        title={t('qualityConcept.requirements.title', { defaultValue: 'Quality requirements' })}
        description={t('qualityConcept.requirements.body', {
          defaultValue: 'What the finished works must achieve, each with the way it will be checked.',
        })}
        action={
          <Button size="sm" variant="secondary" icon={<Plus size={14} />} disabled={!manage} onClick={() => setAddingRequirement(true)} data-testid="requirement-add">
            {t('qualityConcept.requirements.add', { defaultValue: 'Add requirement' })}
          </Button>
        }
      >
        {(requirements.data ?? []).length === 0 ? (
          <Hint testId="requirements-empty">
            {t('qualityConcept.requirements.empty', {
              defaultValue: 'No requirement yet. Start with what matters most to the owner, such as acoustics, energy or durability.',
            })}
          </Hint>
        ) : (
          <ul className="divide-y divide-border-light" data-testid="requirements-list">
            {(requirements.data ?? []).map((r) => (
              <li key={r.id} className="flex flex-wrap items-baseline gap-2 py-2 text-sm">
                <span className="text-xs text-content-tertiary">{nameIn(labels, catalogue?.requirement_categories, r.category)}</span>
                <span className="font-medium text-content-primary">{r.entity}</span>
                <span className="text-content-secondary">{r.attribute}</span>
                <span className="text-content-primary">
                  {r.constraint_value} {r.unit}
                </span>
                {r.verification_method && (
                  <span className="ml-auto text-xs text-content-tertiary">
                    {vocab(t as TFn, VERIFICATION_METHOD, r.verification_method)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {editing && (
        <StandardDialog {...props} standard={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
      )}
      {addingRequirement && <RequirementDialog {...props} onClose={() => setAddingRequirement(false)} />}
      <ConfirmDialog
        open={!!removing}
        variant="danger"
        loading={write.pending}
        title={t('qualityConcept.standards.remove_title', { defaultValue: 'Remove this standard?' })}
        message={t('qualityConcept.standards.remove_body', {
          defaultValue: '{{code}} is taken out of the standards basis of this project.',
          code: removing?.code ?? '',
        })}
        confirmLabel={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
        cancelLabel={t('qualityConcept.common.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const row = removing;
          setRemoving(null);
          if (row) write.send(() => deleteStandard(projectId, row.id));
        }}
      />
    </>
  );
}

function StandardDialog({
  projectId,
  catalogue,
  labels,
  standard,
  onClose,
}: PanelProps & { standard: AppliedStandard | null; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [code, setCode] = useState(standard?.code ?? '');
  const [edition, setEdition] = useState(standard?.edition ?? '');
  const [title, setTitle] = useState(standard?.title ?? '');
  const [family, setFamily] = useState(standard?.family_code ?? '');
  const [mandate, setMandate] = useState<Mandate>(standard?.mandate ?? 'contract');
  const [note, setNote] = useState(standard?.note ?? '');
  const body = { code: code.trim(), edition: edition.trim(), title: title.trim(), family_code: family || null, mandate, note: note.trim() };

  return (
    <FormDialog
      open
      testId="standard-dialog"
      title={
        standard
          ? t('qualityConcept.standards.edit_title', { defaultValue: 'Edit standard' })
          : t('qualityConcept.standards.add', { defaultValue: 'Add standard' })
      }
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={code.trim() ? null : t('qualityConcept.standards.problem_code', { defaultValue: 'Enter the number of the standard' })}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(() => (standard ? patchStandard(projectId, standard.id, body) : createStandard(projectId, body)), onClose)
      }
    >
      <div className="grid gap-3 md:grid-cols-2">
        <Field required label={t('qualityConcept.standards.code', { defaultValue: 'Standard number' })}>
          <input className={inputCls} value={code} onChange={(e) => setCode(e.target.value)} data-testid="standard-code" />
        </Field>
        <Field label={t('qualityConcept.standards.edition', { defaultValue: 'Edition' })}>
          <input className={inputCls} value={edition} onChange={(e) => setEdition(e.target.value)} />
        </Field>
      </div>
      <Field label={t('qualityConcept.standards.name', { defaultValue: 'Title' })}>
        <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={t('qualityConcept.standards.family', { defaultValue: 'Subject area' })}>
          <select className={inputCls} value={family} onChange={(e) => setFamily(e.target.value)}>
            <option value="">{t('qualityConcept.common.none', { defaultValue: 'None' })}</option>
            {(catalogue?.standard_families ?? []).map((f) => (
              <option key={f.code} value={f.code}>
                {catalogueName(labels, f)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('qualityConcept.standards.mandate', { defaultValue: 'Why it applies' })}>
          <VocabSelect map={MANDATE} codes={MANDATES} value={mandate} onChange={(v) => setMandate(v as Mandate)} />
        </Field>
      </div>
      <Field label={t('qualityConcept.common.note', { defaultValue: 'Note' })}>
        <textarea rows={2} className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
    </FormDialog>
  );
}

function RequirementDialog({ projectId, catalogue, labels, onClose }: PanelProps & { onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const categories = catalogue?.requirement_categories ?? [];
  const [picked, setCategory] = useState('');
  const category = picked || categories[0]?.code || '';
  const [entity, setEntity] = useState('');
  const [attribute, setAttribute] = useState('');
  const [value, setValue] = useState('');
  const [unit, setUnit] = useState('');
  const [source, setSource] = useState('');
  const [method, setMethod] = useState('');
  const problem = !category
    ? t('qualityConcept.requirements.problem_category', { defaultValue: 'Choose a category' })
    : !entity.trim() || !attribute.trim()
      ? t('qualityConcept.requirements.problem_subject', { defaultValue: 'Say what the requirement is about and which property it sets' })
      : null;

  return (
    <FormDialog
      open
      testId="requirement-dialog"
      title={t('qualityConcept.requirements.add', { defaultValue: 'Add requirement' })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={problem}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(
          () =>
            addRequirement(projectId, {
              category,
              entity: entity.trim(),
              attribute: attribute.trim(),
              constraint_value: value.trim(),
              unit: unit.trim(),
              source_ref: source.trim(),
              verification_method: method || null,
            }),
          onClose,
        )
      }
    >
      <Field required label={t('qualityConcept.requirements.category', { defaultValue: 'Category' })}>
        <select className={inputCls} value={category} onChange={(e) => setCategory(e.target.value)} data-testid="requirement-category">
          {categories.map((c) => (
            <option key={c.code} value={c.code}>
              {catalogueName(labels, c)}
            </option>
          ))}
        </select>
      </Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field
          required
          label={t('qualityConcept.requirements.entity', { defaultValue: 'What it is about' })}
          hint={t('qualityConcept.requirements.entity_hint', { defaultValue: 'For example: partition walls of the offices' })}
        >
          <input className={inputCls} value={entity} onChange={(e) => setEntity(e.target.value)} data-testid="requirement-entity" />
        </Field>
        <Field
          required
          label={t('qualityConcept.requirements.attribute', { defaultValue: 'Property' })}
          hint={t('qualityConcept.requirements.attribute_hint', { defaultValue: 'For example: sound reduction' })}
        >
          <input className={inputCls} value={attribute} onChange={(e) => setAttribute(e.target.value)} data-testid="requirement-attribute" />
        </Field>
        <Field label={t('qualityConcept.requirements.value', { defaultValue: 'Required value' })}>
          <input className={inputCls} value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
        <Field label={t('qualityConcept.requirements.unit', { defaultValue: 'Unit' })}>
          <input className={inputCls} value={unit} onChange={(e) => setUnit(e.target.value)} />
        </Field>
        <Field label={t('qualityConcept.requirements.source', { defaultValue: 'Where it comes from' })}>
          <input className={inputCls} value={source} onChange={(e) => setSource(e.target.value)} />
        </Field>
        <Field label={t('qualityConcept.requirements.method', { defaultValue: 'How it is checked' })}>
          <VocabSelect
            map={VERIFICATION_METHOD}
            codes={METHODS}
            value={method}
            onChange={setMethod}
            emptyLabel={t('qualityConcept.requirements.method_default', { defaultValue: 'As the category suggests' })}
          />
        </Field>
      </div>
    </FormDialog>
  );
}
