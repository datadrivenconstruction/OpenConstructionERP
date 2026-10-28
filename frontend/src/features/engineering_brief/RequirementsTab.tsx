// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Requirements of the client: a register grouped by category, a hint for the
// required categories nobody has covered yet, and an add / edit dialog.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Pencil, Plus, Trash2 } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal, WideModalField } from '@/shared/ui/WideModal';
import { fmtList } from '@/shared/lib/formatters';

import {
  CONSTRAINT_TYPES,
  PRIORITIES,
  createRequirement,
  deleteRequirement,
  updateRequirement,
  type BriefCatalogue,
  type Can,
  type ConstraintType,
  type Priority,
  type Requirement,
  type RequirementInput,
} from './api';
import { ExportButtons, FIELD_CLASS, FormError, ReadOnlyNotice, useBriefAction, useSubmit } from './BriefBits';
import {
  CONSTRAINT_LABEL,
  PRIORITY_LABEL,
  PRIORITY_TONE,
  itemLabel,
  keyText,
  vocabularyLabel,
  type LabelContext,
  type TFn,
} from './labels';

const EMPTY: RequirementInput = {
  entity: '',
  attribute: '',
  constraint_type: 'equals',
  constraint_value: '',
  unit: '',
  category: '',
  priority: 'must',
  verification_method: '',
  originator: '',
  originator_role: '',
  source_ref: '',
  rationale: '',
  phase: '',
};

/** True when the constraint type takes no value (exists / not_exists). */
function takesNoValue(type: ConstraintType): boolean {
  return type === 'exists' || type === 'not_exists';
}

export function RequirementDialog({
  open,
  projectId,
  catalogue,
  labels,
  editing,
  defaultCategory,
  onClose,
  onDone,
}: {
  open: boolean;
  projectId: string;
  catalogue: BriefCatalogue;
  labels: LabelContext;
  editing: Requirement | null;
  defaultCategory: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<RequirementInput>(EMPTY);
  const [tried, setTried] = useState(false);
  const sub = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (!open) return;
    setTried(false);
    sub.reset();
    if (editing) {
      const { id: _id, status: _status, answered_by: _answered, ...rest } = editing;
      setForm(rest);
    } else {
      setForm({ ...EMPTY, category: defaultCategory || catalogue.requirement_categories[0]?.code || '' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const set = <K extends keyof RequirementInput>(key: K, value: RequirementInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const missing = !form.entity.trim() || !form.attribute.trim() || !form.category;
  const required = t('engineeringBrief.required', { defaultValue: 'Required' });

  const save = () => {
    if (missing) {
      setTried(true);
      return;
    }
    const body: RequirementInput = takesNoValue(form.constraint_type) ? { ...form, constraint_value: '' } : form;
    void sub.run(() => (editing ? updateRequirement(projectId, editing.id, body) : createRequirement(projectId, body)));
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={sub.busy}
      size="lg"
      testId="brief-requirement-dialog"
      title={
        editing
          ? t('engineeringBrief.requirements.edit', { defaultValue: 'Edit requirement' })
          : t('engineeringBrief.requirements.add', { defaultValue: 'Add requirement' })
      }
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <FormError message={sub.error} />
          <Button variant="ghost" onClick={onClose} disabled={sub.busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={sub.busy} onClick={save} data-testid="brief-requirement-save">
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <WideModalField label={t('engineeringBrief.requirements.category', { defaultValue: 'Category' })} required error={tried && !form.category ? required : undefined}>
          <select className={FIELD_CLASS} value={form.category} onChange={(e) => set('category', e.target.value)} data-testid="brief-requirement-category">
            {catalogue.requirement_categories.map((c) => (
              <option key={c.code} value={c.code}>
                {itemLabel(labels, c, c.code)}
              </option>
            ))}
            {form.category && !catalogue.requirement_categories.some((c) => c.code === form.category) ? (
              <option value={form.category}>{form.category}</option>
            ) : null}
          </select>
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.priority', { defaultValue: 'Priority' })}>
          <select className={FIELD_CLASS} value={form.priority} onChange={(e) => set('priority', e.target.value as Priority)}>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {keyText(t as TFn, PRIORITY_LABEL[p])}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.entity', { defaultValue: 'Subject' })} required error={tried && !form.entity.trim() ? required : undefined}>
          <input className={FIELD_CLASS} value={form.entity} maxLength={255} onChange={(e) => set('entity', e.target.value)} data-testid="brief-requirement-entity" />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.attribute', { defaultValue: 'Property' })} required error={tried && !form.attribute.trim() ? required : undefined}>
          <input className={FIELD_CLASS} value={form.attribute} maxLength={255} onChange={(e) => set('attribute', e.target.value)} data-testid="brief-requirement-attribute" />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.constraint', { defaultValue: 'Condition' })}>
          <select className={FIELD_CLASS} value={form.constraint_type} onChange={(e) => set('constraint_type', e.target.value as ConstraintType)}>
            {CONSTRAINT_TYPES.map((c) => (
              <option key={c} value={c}>
                {keyText(t as TFn, CONSTRAINT_LABEL[c])}
              </option>
            ))}
          </select>
        </WideModalField>
        <div className="grid grid-cols-3 gap-2">
          <WideModalField label={t('engineeringBrief.requirements.value', { defaultValue: 'Value' })} className="col-span-2">
            <input className={FIELD_CLASS} value={form.constraint_value} maxLength={500} disabled={takesNoValue(form.constraint_type)} onChange={(e) => set('constraint_value', e.target.value)} />
          </WideModalField>
          <WideModalField label={t('engineeringBrief.requirements.unit', { defaultValue: 'Unit' })}>
            <input className={FIELD_CLASS} value={form.unit} maxLength={50} onChange={(e) => set('unit', e.target.value)} />
          </WideModalField>
        </div>
        <WideModalField label={t('engineeringBrief.requirements.verification', { defaultValue: 'Verification' })}>
          <select className={FIELD_CLASS} value={form.verification_method} onChange={(e) => set('verification_method', e.target.value)}>
            <option value="">{t('engineeringBrief.none', { defaultValue: 'None' })}</option>
            {catalogue.verification_methods.map((m) => (
              <option key={m} value={m}>
                {vocabularyLabel(t as TFn, 'verification', m)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.phase', { defaultValue: 'Phase' })}>
          <select className={FIELD_CLASS} value={form.phase} onChange={(e) => set('phase', e.target.value)}>
            <option value="">{t('engineeringBrief.none', { defaultValue: 'None' })}</option>
            {catalogue.phases.map((p) => (
              <option key={p} value={p}>
                {vocabularyLabel(t as TFn, 'phase', p)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.originator', { defaultValue: 'Originator' })}>
          <input className={FIELD_CLASS} value={form.originator} maxLength={255} onChange={(e) => set('originator', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.originator_role', { defaultValue: 'Originator role' })}>
          <select className={FIELD_CLASS} value={form.originator_role} onChange={(e) => set('originator_role', e.target.value)}>
            <option value="">{t('engineeringBrief.none', { defaultValue: 'None' })}</option>
            {catalogue.originator_roles.map((r) => (
              <option key={r} value={r}>
                {vocabularyLabel(t as TFn, 'role', r)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.source_ref', { defaultValue: 'Source reference' })} span={2}>
          <input className={FIELD_CLASS} value={form.source_ref} maxLength={500} onChange={(e) => set('source_ref', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.requirements.rationale', { defaultValue: 'Rationale' })} span={2}>
          <textarea className={FIELD_CLASS} rows={3} value={form.rationale} maxLength={20000} onChange={(e) => set('rationale', e.target.value)} />
        </WideModalField>
      </div>
    </WideModal>
  );
}

export function RequirementsTab({
  projectId,
  requirements,
  catalogue,
  labels,
  edit,
  onChanged,
}: {
  projectId: string;
  requirements: Requirement[];
  catalogue: BriefCatalogue;
  labels: LabelContext;
  edit: Can;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<{ editing: Requirement | null; category: string } | null>(null);
  const [removing, setRemoving] = useState<Requirement | null>(null);
  const remove = useBriefAction((id: string) => deleteRequirement(projectId, id), () => {
    setRemoving(null);
    onChanged();
  });

  const groups = useMemo(() => {
    const byCategory = new Map<string, Requirement[]>();
    for (const r of requirements) byCategory.set(r.category, [...(byCategory.get(r.category) ?? []), r]);
    const known = catalogue.requirement_categories.map((c) => c.code);
    const order = [...known, ...[...byCategory.keys()].filter((c) => !known.includes(c))];
    return order.filter((c) => byCategory.has(c)).map((c) => ({ code: c, rows: byCategory.get(c) ?? [] }));
  }, [requirements, catalogue]);
  const uncovered = catalogue.requirement_categories.filter((c) => c.required && !requirements.some((r) => r.category === c.code));
  const categoryName = (code: string) => itemLabel(labels, catalogue.requirement_categories.find((c) => c.code === code), code);

  return (
    <div className="space-y-4" data-testid="brief-requirements">
      <ReadOnlyNotice edit={edit} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ExportButtons projectId={projectId} what="requirements" />
        {edit.allowed ? (
          <Button size="sm" icon={<Plus size={14} />} onClick={() => setDialog({ editing: null, category: '' })} data-testid="brief-requirement-add">
            {t('engineeringBrief.requirements.add', { defaultValue: 'Add requirement' })}
          </Button>
        ) : null}
      </div>

      {uncovered.length > 0 ? (
        <div className="flex items-start gap-2 rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-sm" data-testid="brief-uncovered">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          <div>
            <p className="text-content-primary">
              {t('engineeringBrief.requirements.uncovered', { defaultValue: 'Required categories without a requirement yet:' })}
            </p>
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {uncovered.map((c) => (
                <li key={c.code}>
                  {edit.allowed ? (
                    <button type="button" className="rounded-full border border-border-light px-2 py-0.5 text-xs text-content-primary hover:bg-surface-primary" onClick={() => setDialog({ editing: null, category: c.code })}>
                      {itemLabel(labels, c, c.code)}
                    </button>
                  ) : (
                    <span className="rounded-full border border-border-light px-2 py-0.5 text-xs text-content-primary">{itemLabel(labels, c, c.code)}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      {groups.length === 0 ? (
        <EmptyState
          title={t('engineeringBrief.requirements.empty_title', { defaultValue: 'No requirements yet' })}
          description={t('engineeringBrief.requirements.empty_body', {
            defaultValue: 'Record what the client needs from the building and its operation, one requirement per line.',
          })}
        />
      ) : (
        groups.map((g) => {
          const category = catalogue.requirement_categories.find((c) => c.code === g.code);
          return (
            <section key={g.code} className="space-y-1.5" data-testid={`brief-requirements-group-${g.code}`}>
              <h3 className="text-sm font-semibold text-content-primary">
                {categoryName(g.code)}
                {category?.reference ? <span className="ml-2 text-xs font-normal text-content-tertiary">{category.reference}</span> : null}
              </h3>
              <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
                    <tr>
                      <th className="px-3 py-2">{t('engineeringBrief.requirements.entity', { defaultValue: 'Subject' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.requirements.attribute', { defaultValue: 'Property' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.requirements.constraint', { defaultValue: 'Condition' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.requirements.priority', { defaultValue: 'Priority' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.requirements.verification', { defaultValue: 'Verification' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.requirements.answered', { defaultValue: 'Concept' })}</th>
                      <th className="w-20 px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {g.rows.map((r) => (
                      <tr key={r.id} className="border-t border-border-light" data-testid="brief-requirement-row">
                        <td className="px-3 py-2 text-content-primary">{r.entity}</td>
                        <td className="px-3 py-2 text-content-primary">{r.attribute}</td>
                        <td className="px-3 py-2 text-content-secondary">
                          {keyText(t as TFn, CONSTRAINT_LABEL[r.constraint_type])} {r.constraint_value} {r.unit}
                        </td>
                        <td className="px-3 py-2">
                          <Badge variant={PRIORITY_TONE[r.priority]} size="sm">
                            {keyText(t as TFn, PRIORITY_LABEL[r.priority])}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-content-secondary">{vocabularyLabel(t as TFn, 'verification', r.verification_method) || '-'}</td>
                        <td className="px-3 py-2 font-mono text-xs text-content-secondary">{fmtList(r.answered_by) || '-'}</td>
                        <td className="px-3 py-2">
                          {edit.allowed ? (
                            <div className="flex justify-end gap-1">
                              <Button variant="ghost" size="sm" aria-label={t('common.edit', { defaultValue: 'Edit' })} icon={<Pencil size={14} />} onClick={() => setDialog({ editing: r, category: r.category })} />
                              <Button variant="ghost" size="sm" aria-label={t('common.delete', { defaultValue: 'Delete' })} icon={<Trash2 size={14} />} onClick={() => setRemoving(r)} />
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          );
        })
      )}

      <RequirementDialog
        open={dialog !== null}
        projectId={projectId}
        catalogue={catalogue}
        labels={labels}
        editing={dialog?.editing ?? null}
        defaultCategory={dialog?.category ?? ''}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <ConfirmDialog
        open={removing !== null}
        title={t('engineeringBrief.requirements.delete_title', { defaultValue: 'Delete requirement' })}
        message={t('engineeringBrief.requirements.delete_body', { defaultValue: 'This requirement is removed from the brief.' })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
