// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The site analysis and the suitability studies of the project. Each group
// says whether it meets the gate criterion: at least one study, every study
// concluded with a result, every study backed by a report document. The report
// is picked from the project's documents. Studies stay editable in every state
// of the brief.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { CheckCircle2, CircleAlert, Pencil, Plus, Trash2 } from 'lucide-react';

import type { DocumentItem } from '@/features/documents/api';
import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal, WideModalField } from '@/shared/ui/WideModal';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  createStudy,
  deleteStudy,
  STUDY_CONCLUSIONS,
  STUDY_KINDS,
  updateStudy,
  type Study,
  type StudyConclusion,
  type StudyInput,
  type StudyKind,
} from './api';
import { FIELD_CLASS, FormError, useBriefAction, useSubmit } from './BriefBits';
import { useProjectDocuments } from './hooks';
import { keyText, type KeyText, type TFn } from './labels';

export const STUDY_KIND_LABEL: Record<StudyKind, KeyText> = {
  site_analysis: ['engineeringBrief.studies.kind.site_analysis', 'Site analysis'],
  suitability: ['engineeringBrief.studies.kind.suitability', 'Suitability studies'],
};

export const STUDY_CONCLUSION_LABEL: Record<StudyConclusion, KeyText> = {
  open: ['engineeringBrief.studies.conclusion.open', 'Open'],
  suitable: ['engineeringBrief.studies.conclusion.suitable', 'Suitable'],
  conditional: ['engineeringBrief.studies.conclusion.conditional', 'Suitable with conditions'],
  unsuitable: ['engineeringBrief.studies.conclusion.unsuitable', 'Unsuitable'],
};

const CONCLUSION_TONE: Record<StudyConclusion, BadgeVariant> = {
  open: 'neutral',
  suitable: 'success',
  conditional: 'warning',
  unsuitable: 'error',
};

/** The documents module page that shows one document. */
export function documentLink(documentId: string): string {
  return `/files?file=${encodeURIComponent(documentId)}`;
}

export type StudyGate =
  | { met: true }
  | { met: false; reason: 'no_study' | 'study_open' | 'study_without_document'; codes: string[] };

/** The gate criterion of one group, the same rule as the server: studies exist, all concluded with a result, all documented. */
export function studyGate(kind: StudyKind, studies: Study[]): StudyGate {
  const rows = studies.filter((s) => s.kind === kind);
  if (rows.length === 0) return { met: false, reason: 'no_study', codes: [] };
  const open = rows.filter((s) => s.conclusion === 'open' || !s.result.trim()).map((s) => s.code);
  if (open.length > 0) return { met: false, reason: 'study_open', codes: open.sort() };
  const bare = rows.filter((s) => !s.document_id).map((s) => s.code);
  if (bare.length > 0) return { met: false, reason: 'study_without_document', codes: bare.sort() };
  return { met: true };
}

const EMPTY: StudyInput = {
  kind: 'site_analysis',
  title: '',
  scope: '',
  author: '',
  study_date: null,
  result: '',
  conclusion: 'open',
  document_id: null,
};

function StudyDialog({
  open,
  projectId,
  editing,
  defaultKind,
  onClose,
  onDone,
}: {
  open: boolean;
  projectId: string;
  editing: Study | null;
  defaultKind: StudyKind;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<StudyInput>(EMPTY);
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
      setForm({
        kind: editing.kind,
        title: editing.title,
        scope: editing.scope,
        author: editing.author,
        study_date: editing.study_date,
        result: editing.result,
        conclusion: editing.conclusion,
        document_id: editing.document_id,
      });
    } else {
      setForm({ ...EMPTY, kind: defaultKind });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing, defaultKind]);

  const required = t('engineeringBrief.required', { defaultValue: 'Required' });
  const save = () => {
    if (!form.title.trim()) {
      setTried(true);
      return;
    }
    void sub.run(() => (editing ? updateStudy(projectId, editing.id, form) : createStudy(projectId, form)));
  };
  const [search, setSearch] = useState('');
  const [wanted, setWanted] = useState(50);
  const [term, setTerm] = useState('');
  useEffect(() => {
    const id = window.setTimeout(() => {
      setTerm(search);
      setWanted(50);
    }, 300);
    return () => window.clearTimeout(id);
  }, [search]);
  const docsQ = useProjectDocuments(projectId, open, term, wanted);
  const documents: DocumentItem[] = docsQ.data?.items ?? [];
  const moreDocuments = (docsQ.data?.total ?? 0) > documents.length;
  // A linked document that is not in the list (another page of the register) stays selectable under its stored name.
  const linkedMissing = !!form.document_id && !documents.some((d) => d.id === form.document_id);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={sub.busy}
      size="md"
      testId="brief-study-dialog"
      title={
        editing
          ? t('engineeringBrief.studies.edit', { defaultValue: 'Edit study' })
          : t('engineeringBrief.studies.add', { defaultValue: 'Add study' })
      }
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <FormError message={sub.error} />
          <Button variant="ghost" onClick={onClose} disabled={sub.busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={sub.busy} onClick={save} data-testid="brief-study-save">
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <WideModalField label={t('engineeringBrief.studies.kind', { defaultValue: 'Kind' })} required>
            <select className={FIELD_CLASS} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as StudyKind })} data-testid="brief-study-kind">
              {STUDY_KINDS.map((k) => (
                <option key={k} value={k}>
                  {keyText(t as TFn, STUDY_KIND_LABEL[k])}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('engineeringBrief.studies.conclusion', { defaultValue: 'Conclusion' })} required>
            <select className={FIELD_CLASS} value={form.conclusion} onChange={(e) => setForm({ ...form, conclusion: e.target.value as StudyConclusion })} data-testid="brief-study-conclusion">
              {STUDY_CONCLUSIONS.map((c) => (
                <option key={c} value={c}>
                  {keyText(t as TFn, STUDY_CONCLUSION_LABEL[c])}
                </option>
              ))}
            </select>
          </WideModalField>
        </div>
        <WideModalField label={t('engineeringBrief.studies.title', { defaultValue: 'Title' })} required error={tried && !form.title.trim() ? required : undefined}>
          <input className={FIELD_CLASS} value={form.title} maxLength={255} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="brief-study-title" />
        </WideModalField>
        <div className="grid grid-cols-2 gap-3">
          <WideModalField label={t('engineeringBrief.studies.author', { defaultValue: 'Author' })}>
            <input className={FIELD_CLASS} value={form.author} maxLength={255} onChange={(e) => setForm({ ...form, author: e.target.value })} />
          </WideModalField>
          <WideModalField label={t('engineeringBrief.studies.date', { defaultValue: 'Date' })}>
            <input type="date" className={FIELD_CLASS} value={form.study_date ?? ''} onChange={(e) => setForm({ ...form, study_date: e.target.value || null })} />
          </WideModalField>
        </div>
        <WideModalField label={t('engineeringBrief.studies.scope', { defaultValue: 'Scope' })}>
          <textarea className={FIELD_CLASS} rows={2} value={form.scope} maxLength={20000} onChange={(e) => setForm({ ...form, scope: e.target.value })} />
        </WideModalField>
        <WideModalField label={t('engineeringBrief.studies.result', { defaultValue: 'Result' })}>
          <textarea className={FIELD_CLASS} rows={3} value={form.result} maxLength={20000} onChange={(e) => setForm({ ...form, result: e.target.value })} data-testid="brief-study-result" />
        </WideModalField>
        <WideModalField
          label={t('engineeringBrief.studies.document', { defaultValue: 'Report document' })}
          hint={t('engineeringBrief.studies.document_hint', { defaultValue: 'Pick a document of this project. Upload the report in the documents module first.' })}
        >
          <input
            type="search"
            className={`${FIELD_CLASS} mb-2`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('engineeringBrief.studies.document_search', { defaultValue: 'Search documents by name' })}
            aria-label={t('engineeringBrief.studies.document_search', { defaultValue: 'Search documents by name' })}
            data-testid="brief-study-document-search"
          />
          <select className={FIELD_CLASS} value={form.document_id ?? ''} onChange={(e) => setForm({ ...form, document_id: e.target.value || null })} data-testid="brief-study-document">
            <option value="">{t('engineeringBrief.studies.no_document', { defaultValue: 'No document' })}</option>
            {documents.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
            {linkedMissing && form.document_id ? <option value={form.document_id}>{editing?.document_name || form.document_id}</option> : null}
          </select>
          {moreDocuments && (
            <button
              type="button"
              className="mt-1 text-xs text-oe-blue hover:underline"
              onClick={() => setWanted((n) => n + 50)}
              data-testid="brief-study-document-more"
            >
              {t('engineeringBrief.studies.document_more', { defaultValue: 'Show more documents' })}
            </button>
          )}
        </WideModalField>
      </div>
    </WideModal>
  );
}

function GateIndicator({ kind, gate }: { kind: StudyKind; gate: StudyGate }) {
  const { t } = useTranslation();
  if (gate.met) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-semantic-success" data-testid={`brief-studies-gate-${kind}`} data-met="true">
        <CheckCircle2 size={14} aria-hidden />
        {t('engineeringBrief.studies.gate_met', { defaultValue: 'Criterion met: all studies concluded and documented' })}
      </span>
    );
  }
  const codes = fmtList(gate.codes);
  const reason =
    gate.reason === 'no_study'
      ? t('engineeringBrief.studies.gate_no_study', { defaultValue: 'no study recorded yet' })
      : gate.reason === 'study_open'
        ? t('engineeringBrief.studies.gate_open', { defaultValue: 'still open or without a result: {{codes}}', codes })
        : t('engineeringBrief.studies.gate_undocumented', { defaultValue: 'without a report document: {{codes}}', codes });
  return (
    <span className="flex items-center gap-1.5 text-xs text-semantic-warning" data-testid={`brief-studies-gate-${kind}`} data-met="false">
      <CircleAlert size={14} aria-hidden />
      {t('engineeringBrief.studies.gate_not_met', { defaultValue: 'Criterion not met: {{reason}}', reason })}
    </span>
  );
}

export function StudiesTab({
  projectId,
  studies,
  canWrite,
  onChanged,
}: {
  projectId: string;
  studies: Study[];
  /** False when the caller lacks the edit permission: the tab then only reads. */
  canWrite: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<{ editing: Study | null; kind: StudyKind } | null>(null);
  const [removing, setRemoving] = useState<Study | null>(null);
  const remove = useBriefAction((id: string) => deleteStudy(projectId, id), () => {
    setRemoving(null);
    onChanged();
  });

  return (
    <div className="space-y-6" data-testid="brief-studies">
      {STUDY_KINDS.map((kind) => {
        const rows = studies.filter((s) => s.kind === kind);
        return (
          <section key={kind} className="space-y-2" data-testid={`brief-studies-group-${kind}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="space-y-0.5">
                <h3 className="text-sm font-semibold text-content-primary">{keyText(t as TFn, STUDY_KIND_LABEL[kind])}</h3>
                <GateIndicator kind={kind} gate={studyGate(kind, studies)} />
              </div>
              {canWrite ? (
                <Button size="sm" icon={<Plus size={14} />} onClick={() => setDialog({ editing: null, kind })} data-testid={`brief-study-add-${kind}`}>
                  {t('engineeringBrief.studies.add', { defaultValue: 'Add study' })}
                </Button>
              ) : null}
            </div>
            {rows.length === 0 ? (
              <EmptyState
                title={t('engineeringBrief.studies.empty_title', { defaultValue: 'No studies yet' })}
                description={t('engineeringBrief.studies.empty_body', {
                  defaultValue: 'Record each study with its result and link the report from the documents module.',
                })}
              />
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border-light">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
                    <tr>
                      <th className="px-3 py-2">{t('engineeringBrief.studies.code', { defaultValue: 'No.' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.studies.title', { defaultValue: 'Title' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.studies.author', { defaultValue: 'Author' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.studies.date', { defaultValue: 'Date' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.studies.conclusion', { defaultValue: 'Conclusion' })}</th>
                      <th className="px-3 py-2">{t('engineeringBrief.studies.document', { defaultValue: 'Report document' })}</th>
                      <th className="w-20 px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((s) => (
                      <tr key={s.id} className="border-t border-border-light" data-testid="brief-study-row">
                        <td className="px-3 py-2 font-mono text-xs text-content-tertiary">{s.code}</td>
                        <td className="px-3 py-2 text-content-primary">{s.title}</td>
                        <td className="px-3 py-2 text-content-secondary">{s.author || '-'}</td>
                        <td className="px-3 py-2 text-content-secondary">{s.study_date ? fmtDate(s.study_date) : '-'}</td>
                        <td className="px-3 py-2">
                          <Badge variant={CONCLUSION_TONE[s.conclusion]} size="sm">
                            {keyText(t as TFn, STUDY_CONCLUSION_LABEL[s.conclusion])}
                          </Badge>
                        </td>
                        <td className="px-3 py-2">
                          {s.document_id ? (
                            <Link to={documentLink(s.document_id)} className="text-oe-blue hover:underline" data-testid="brief-study-document-link">
                              {s.document_name || t('engineeringBrief.studies.open_document', { defaultValue: 'Open document' })}
                            </Link>
                          ) : (
                            <span className="text-content-tertiary">-</span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {canWrite ? (
                            <div className="flex justify-end gap-1">
                              <Button variant="ghost" size="sm" aria-label={t('common.edit', { defaultValue: 'Edit' })} icon={<Pencil size={14} />} onClick={() => setDialog({ editing: s, kind: s.kind })} />
                              <Button variant="ghost" size="sm" aria-label={t('common.delete', { defaultValue: 'Delete' })} icon={<Trash2 size={14} />} onClick={() => setRemoving(s)} />
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        );
      })}

      <StudyDialog
        open={dialog !== null}
        projectId={projectId}
        editing={dialog?.editing ?? null}
        defaultKind={dialog?.kind ?? 'site_analysis'}
        onClose={() => setDialog(null)}
        onDone={onChanged}
      />
      <ConfirmDialog
        open={removing !== null}
        title={t('engineeringBrief.studies.delete_title', { defaultValue: 'Delete study' })}
        message={t('engineeringBrief.studies.delete_body', { defaultValue: 'This study is removed from the brief. The report document stays in the documents module.' })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
