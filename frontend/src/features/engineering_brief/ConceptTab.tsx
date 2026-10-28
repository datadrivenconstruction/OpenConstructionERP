// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The technical concept: one item per topic with the decision taken, the
// requirements it answers, and whether it is agreed.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ListPlus, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal, WideModalField } from '@/shared/ui/WideModal';

import {
  conceptsFromCatalogue,
  createConcept,
  deleteConcept,
  setConceptStatus,
  updateConcept,
  type BriefCatalogue,
  type Can,
  type ConceptInput,
  type ConceptItem,
  type Requirement,
} from './api';
import { ExportButtons, FIELD_CLASS, FormError, ReadOnlyNotice, useBriefAction, useSubmit } from './BriefBits';
import { CONCEPT_STATUS, itemLabel, keyText, type LabelContext, type TFn } from './labels';

const EMPTY: ConceptInput = { topic_code: '', title: '', description: '', decision: '', requirement_ids: [] };

function ConceptDialog({
  open,
  projectId,
  catalogue,
  labels,
  requirements,
  editing,
  defaultTopic,
  onClose,
  onDone,
}: {
  open: boolean;
  projectId: string;
  catalogue: BriefCatalogue;
  labels: LabelContext;
  requirements: Requirement[];
  editing: ConceptItem | null;
  defaultTopic: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<ConceptInput>(EMPTY);
  const [tried, setTried] = useState(false);
  const sub = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (!open) return;
    setTried(false);
    sub.reset();
    setForm(
      editing
        ? {
            topic_code: editing.topic_code,
            title: editing.title,
            description: editing.description,
            decision: editing.decision,
            requirement_ids: editing.requirement_ids,
          }
        : { ...EMPTY, topic_code: defaultTopic || catalogue.concept_topics[0]?.code || '' },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const toggle = (id: string) =>
    setForm((f) => ({
      ...f,
      requirement_ids: f.requirement_ids.includes(id) ? f.requirement_ids.filter((x) => x !== id) : [...f.requirement_ids, id],
    }));
  const save = () => {
    if (!form.title.trim() || !form.topic_code) {
      setTried(true);
      return;
    }
    void sub.run(() => (editing ? updateConcept(projectId, editing.id, form) : createConcept(projectId, form)));
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={sub.busy}
      size="lg"
      testId="brief-concept-dialog"
      title={
        editing
          ? t('engineeringBrief.concept.edit', { defaultValue: 'Edit concept item' })
          : t('engineeringBrief.concept.add', { defaultValue: 'Add concept item' })
      }
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <FormError message={sub.error} />
          <Button variant="ghost" onClick={onClose} disabled={sub.busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={sub.busy} onClick={save} data-testid="brief-concept-save">
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <WideModalField label={t('engineeringBrief.concept.topic', { defaultValue: 'Topic' })} required>
          <select className={FIELD_CLASS} value={form.topic_code} onChange={(e) => setForm({ ...form, topic_code: e.target.value })}>
            {catalogue.concept_topics.map((c) => (
              <option key={c.code} value={c.code}>
                {itemLabel(labels, c, c.code)}
              </option>
            ))}
            {form.topic_code && !catalogue.concept_topics.some((c) => c.code === form.topic_code) ? (
              <option value={form.topic_code}>{form.topic_code}</option>
            ) : null}
          </select>
        </WideModalField>
        <WideModalField
          label={t('engineeringBrief.field.title', { defaultValue: 'Title' })}
          required
          error={tried && !form.title.trim() ? t('engineeringBrief.required', { defaultValue: 'Required' }) : undefined}
        >
          <input className={FIELD_CLASS} value={form.title} maxLength={255} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="brief-concept-title" />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.concept.description', { defaultValue: 'Description' })}>
          <textarea className={FIELD_CLASS} rows={3} value={form.description} maxLength={20000} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </WideModalField>
        <WideModalField
          label={t('engineeringBrief.concept.decision', { defaultValue: 'Decision' })}
          hint={t('engineeringBrief.concept.decision_hint', { defaultValue: 'A written decision marks the item as agreed.' })}
        >
          <textarea className={FIELD_CLASS} rows={3} value={form.decision} maxLength={20000} onChange={(e) => setForm({ ...form, decision: e.target.value })} data-testid="brief-concept-decision" />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.concept.requirements', { defaultValue: 'Requirements answered' })}>
          {requirements.length === 0 ? (
            <p className="text-sm text-content-secondary">{t('engineeringBrief.concept.no_requirements', { defaultValue: 'There are no requirements to link yet.' })}</p>
          ) : (
            <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border-light bg-surface-elevated p-2">
              {requirements.map((r) => (
                <li key={r.id}>
                  <label className="flex items-start gap-2 text-sm text-content-primary">
                    <input type="checkbox" className="mt-1" checked={form.requirement_ids.includes(r.id)} onChange={() => toggle(r.id)} />
                    <span>
                      {r.entity} / {r.attribute}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </WideModalField>
      </div>
    </WideModal>
  );
}

export function ConceptTab({
  projectId,
  items,
  requirements,
  catalogue,
  labels,
  edit,
  onChanged,
}: {
  projectId: string;
  items: ConceptItem[];
  requirements: Requirement[];
  catalogue: BriefCatalogue;
  labels: LabelContext;
  edit: Can;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<{ editing: ConceptItem | null; topic: string } | null>(null);
  const [removing, setRemoving] = useState<ConceptItem | null>(null);
  const fromCatalogue = useBriefAction(() => conceptsFromCatalogue(projectId), onChanged);
  const status = useBriefAction(
    ({ id, agreed }: { id: string; agreed: boolean }) => setConceptStatus(projectId, id, agreed ? 'agreed' : 'open'),
    onChanged,
  );
  const remove = useBriefAction((id: string) => deleteConcept(projectId, id), () => {
    setRemoving(null);
    onChanged();
  });

  const topicName = (code: string) => itemLabel(labels, catalogue.concept_topics.find((c) => c.code === code), code);
  const known = catalogue.concept_topics.map((c) => c.code);
  const order = [...known, ...items.map((i) => i.topic_code).filter((c) => !known.includes(c))];
  const topics = order.filter((c, i) => order.indexOf(c) === i && items.some((it) => it.topic_code === c));
  const requirementName = (id: string) => {
    const r = requirements.find((x) => x.id === id);
    return r ? `${r.entity} / ${r.attribute}` : id;
  };

  return (
    <div className="space-y-4" data-testid="brief-concept">
      <ReadOnlyNotice edit={edit} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ExportButtons projectId={projectId} what="concept" />
        {edit.allowed ? (
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" icon={<ListPlus size={14} />} loading={fromCatalogue.isPending} onClick={() => fromCatalogue.mutate()} data-testid="brief-concept-from-catalogue">
              {t('engineeringBrief.concept.from_catalogue', { defaultValue: 'Create from catalogue' })}
            </Button>
            <Button size="sm" icon={<Plus size={14} />} onClick={() => setDialog({ editing: null, topic: '' })} data-testid="brief-concept-add">
              {t('engineeringBrief.concept.add', { defaultValue: 'Add concept item' })}
            </Button>
          </div>
        ) : null}
      </div>

      {topics.length === 0 ? (
        <EmptyState
          title={t('engineeringBrief.concept.empty_title', { defaultValue: 'No concept items yet' })}
          description={t('engineeringBrief.concept.empty_body', {
            defaultValue: 'Create one open item for every topic the catalogue asks for, then write the decision for each.',
          })}
        />
      ) : (
        topics.map((code) => (
          <section key={code} className="space-y-1.5" data-testid={`brief-concept-topic-${code}`}>
            <h3 className="text-sm font-semibold text-content-primary">{topicName(code)}</h3>
            <ul className="space-y-2">
              {items
                .filter((i) => i.topic_code === code)
                .map((i) => (
                  <li key={i.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="brief-concept-row">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-content-primary">
                          <span className="mr-2 font-mono text-xs text-content-tertiary">{i.code}</span>
                          {i.title}
                        </p>
                        {i.description ? <p className="mt-1 text-sm text-content-secondary">{i.description}</p> : null}
                        <p className="mt-1 text-sm text-content-primary">
                          <span className="text-content-secondary">{t('engineeringBrief.concept.decision', { defaultValue: 'Decision' })}: </span>
                          {i.decision || t('engineeringBrief.concept.undecided', { defaultValue: 'Not decided yet' })}
                        </p>
                        {i.requirement_ids.length > 0 ? (
                          <p className="mt-1 text-xs text-content-secondary">
                            {t('engineeringBrief.concept.requirements', { defaultValue: 'Requirements answered' })}: {i.requirement_ids.map(requirementName).join('; ')}
                          </p>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-1">
                        <span data-testid="brief-concept-status">
                          <Badge variant={i.status === 'agreed' ? 'success' : 'warning'} size="sm">
                            {keyText(t as TFn, CONCEPT_STATUS[i.status])}
                          </Badge>
                        </span>
                        {edit.allowed ? (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={i.status === 'agreed' ? <RotateCcw size={14} /> : <Check size={14} />}
                              onClick={() => status.mutate({ id: i.id, agreed: i.status !== 'agreed' })}
                              data-testid="brief-concept-toggle"
                            >
                              {i.status === 'agreed'
                                ? t('engineeringBrief.concept.reopen', { defaultValue: 'Reopen' })
                                : t('engineeringBrief.concept.mark_agreed', { defaultValue: 'Mark agreed' })}
                            </Button>
                            <Button variant="ghost" size="sm" aria-label={t('common.edit', { defaultValue: 'Edit' })} icon={<Pencil size={14} />} onClick={() => setDialog({ editing: i, topic: i.topic_code })} />
                            <Button variant="ghost" size="sm" aria-label={t('common.delete', { defaultValue: 'Delete' })} icon={<Trash2 size={14} />} onClick={() => setRemoving(i)} />
                          </>
                        ) : null}
                      </div>
                    </div>
                  </li>
                ))}
            </ul>
          </section>
        ))
      )}

      <ConceptDialog
        open={dialog !== null}
        projectId={projectId}
        catalogue={catalogue}
        labels={labels}
        requirements={requirements}
        editing={dialog?.editing ?? null}
        defaultTopic={dialog?.topic ?? ''}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <ConfirmDialog
        open={removing !== null}
        title={t('engineeringBrief.concept.delete_title', { defaultValue: 'Delete concept item' })}
        message={t('engineeringBrief.concept.delete_body', { defaultValue: 'This concept item is removed from the brief.' })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
