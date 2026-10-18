// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One snapshot, opened. A draft is where the month's forecast gets its
// reasons: every line that moved by more than the project's threshold since
// the last frozen snapshot asks for a comment and a piece of evidence (a
// document from the register, the minutes of a meeting). When nothing is
// missing, the draft is frozen and from then on it is a record that nobody
// can change. A frozen snapshot opens read-only with its reasons.
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Lock, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';

import { Button, Skeleton } from '@/shared/ui';
import { SideDrawer } from '@/shared/ui/SideDrawer';
import { fmtCurrency, fmtDate, fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fetchDocuments } from '@/features/documents/api';
import { EVIDENCE_KINDS, costControlApi, num, type EvidenceKind, type SnapshotDetail, type SnapshotLine } from './api';
import { evidenceKindLabel, methodLabel, snapshotStatusLabel, sourceLabel, stageLabel } from './labels';

interface EvidenceDraft {
  kind: EvidenceKind;
  ref: string;
  document_id: string | null;
}

function lineTitle(t: ReturnType<typeof useTranslation>['t'], line: SnapshotLine): string {
  if (line.kind === 'unassigned') return t('cost_control.row_unassigned', { defaultValue: 'Not on any cost line' });
  if (line.kind === 'changes_without_contract')
    return t('cost_control.row_loose_changes', { defaultValue: 'Approved changes not on a contract' });
  return `${line.code} ${line.description}`.trim();
}

function NoteEditor({
  projectId,
  snapshotId,
  line,
  onSaved,
}: {
  projectId: string;
  snapshotId: string;
  line: SnapshotLine;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [comment, setComment] = useState(line.comment);
  const [evidence, setEvidence] = useState<EvidenceDraft[]>(
    line.evidence.length > 0
      ? line.evidence.map((e) => ({ kind: e.kind, ref: e.ref, document_id: e.document_id }))
      : [{ kind: 'document', ref: '', document_id: null }],
  );
  const documents = useQuery({
    queryKey: ['cost-control', 'documents', projectId],
    queryFn: () => fetchDocuments(projectId, { limit: 200 }),
    staleTime: 60_000,
  });

  const save = useMutation({
    mutationFn: () =>
      costControlApi.putNote(snapshotId, line.key, {
        comment: comment.trim(),
        evidence: evidence
          .filter((e) => e.ref.trim() || e.document_id)
          .map((e) => ({ kind: e.kind, ref: e.ref.trim(), document_id: e.document_id })),
      }),
    onSuccess: () => {
      onSaved();
      addToast({ type: 'success', title: t('cost_control.note_saved', { defaultValue: 'Reason saved' }) });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.note_failed', { defaultValue: 'Could not save the reason' }),
        message: getErrorMessage(err),
      }),
  });

  const update = (i: number, patch: Partial<EvidenceDraft>) =>
    setEvidence((list) => list.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  const docs = documents.data?.items ?? [];
  const complete = comment.trim().length >= 3 && evidence.some((e) => e.ref.trim() || e.document_id);

  return (
    <form
      className="mt-3 space-y-3 rounded-lg bg-surface-secondary/50 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="block text-sm">
        <span className="text-content-secondary">{t('cost_control.note_comment', { defaultValue: 'Why it moved' })}</span>
        <textarea
          className="mt-1 w-full rounded-lg border border-border bg-surface-primary px-3 py-2"
          rows={2}
          maxLength={4000}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={t('cost_control.note_comment_placeholder', {
            defaultValue: 'e.g. second offer after the clarification round is 6% higher',
          })}
        />
      </label>
      <fieldset className="space-y-2">
        <legend className="text-sm text-content-secondary">
          {t('cost_control.note_evidence', { defaultValue: 'Evidence' })}
        </legend>
        {evidence.map((e, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <select
              className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-sm"
              value={e.kind}
              aria-label={t('cost_control.note_evidence_kind', { defaultValue: 'Kind of evidence' })}
              onChange={(ev) => update(i, { kind: ev.target.value as EvidenceKind, document_id: null })}
            >
              {EVIDENCE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {evidenceKindLabel(t, k)}
                </option>
              ))}
            </select>
            {e.kind === 'document' && docs.length > 0 && (
              <select
                className="h-8 min-w-0 flex-1 rounded-lg border border-border bg-surface-primary px-2 text-sm"
                value={e.document_id ?? ''}
                aria-label={t('cost_control.note_pick_document', { defaultValue: 'Document from the register' })}
                onChange={(ev) => {
                  const doc = docs.find((d) => d.id === ev.target.value);
                  update(i, { document_id: doc?.id ?? null, ref: doc ? doc.name : e.ref });
                }}
              >
                <option value="">
                  {t('cost_control.note_pick_document_none', { defaultValue: 'Pick from the document register' })}
                </option>
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            )}
            <input
              className="h-8 min-w-0 flex-1 rounded-lg border border-border bg-surface-primary px-2 text-sm"
              value={e.ref}
              maxLength={500}
              onChange={(ev) => update(i, { ref: ev.target.value })}
              aria-label={t('cost_control.note_ref', { defaultValue: 'Reference' })}
              placeholder={
                e.kind === 'minutes'
                  ? t('cost_control.note_ref_minutes', { defaultValue: 'e.g. site meeting 14, item 3' })
                  : t('cost_control.note_ref_document', { defaultValue: 'e.g. offer of 12 October' })
              }
            />
            <button
              type="button"
              className="rounded p-1 text-content-quaternary hover:text-semantic-error"
              onClick={() => setEvidence((list) => list.filter((_, j) => j !== i))}
              aria-label={t('cost_control.note_evidence_remove', { defaultValue: 'Remove this evidence' })}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {evidence.length < 20 && (
          <button
            type="button"
            className="flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
            onClick={() => setEvidence((list) => [...list, { kind: 'document', ref: '', document_id: null }])}
          >
            <Plus size={12} />
            {t('cost_control.note_evidence_add', { defaultValue: 'Add evidence' })}
          </button>
        )}
      </fieldset>
      <div className="flex items-center justify-end gap-3">
        {line.needs_evidence && !complete && (
          <span className="text-xs text-content-tertiary">
            {t('cost_control.note_needs_both', { defaultValue: 'A comment and at least one piece of evidence are needed.' })}
          </span>
        )}
        <Button variant="primary" size="sm" type="submit" icon={<Save size={14} />} disabled={save.isPending}>
          {t('cost_control.note_save', { defaultValue: 'Save reason' })}
        </Button>
      </div>
    </form>
  );
}

function LineCard({
  projectId,
  detail,
  line,
  currency,
  editable,
  onSaved,
}: {
  projectId: string;
  detail: SnapshotDetail;
  line: SnapshotLine;
  currency: string;
  editable: boolean;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const delta = num(line.delta);
  const hasNote = !!line.comment || line.evidence.length > 0;
  return (
    <li className="py-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0">
          {line.needs_evidence && !line.documented ? (
            <AlertTriangle size={16} className="text-amber-500" />
          ) : line.documented ? (
            <CheckCircle2 size={16} className="text-semantic-success" />
          ) : (
            <span className="inline-block h-4 w-4" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-sm text-content-primary">{lineTitle(t, line)}</span>
            <span className="shrink-0 text-sm font-medium tabular-nums text-content-primary">
              {fmtCurrency(line.forecast, currency)}
            </span>
          </div>
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-content-tertiary">
            <span>
              {methodLabel(t, line.method)} · {sourceLabel(t, line.source)}
            </span>
            {line.previous !== null && Math.abs(delta) >= 0.005 && (
              <span className={`tabular-nums ${delta > 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
                {t('cost_control.snapshot_moved', {
                  defaultValue: 'from {{before}}: {{delta}}',
                  before: fmtCurrency(line.previous, currency),
                  delta: `${delta > 0 ? '+' : ''}${fmtCurrency(line.delta, currency)}${
                    line.delta_pct ? ` (${delta > 0 ? '+' : ''}${fmtNumber(line.delta_pct, 1)}%)` : ''
                  }`,
                })}
              </span>
            )}
            {line.previous === null && detail.previous && (
              <span>{t('cost_control.snapshot_new_line', { defaultValue: 'new since the last snapshot' })}</span>
            )}
          </div>
          {hasNote && !open && (
            <div className="mt-1.5 text-xs text-content-secondary">
              {line.comment && <p>{line.comment}</p>}
              {line.evidence.length > 0 && (
                <p className="text-content-tertiary">
                  {line.evidence.map((e) => `${evidenceKindLabel(t, e.kind)}: ${e.ref}`).join(' · ')}
                </p>
              )}
            </div>
          )}
          {editable && !open && (
            <button
              type="button"
              className="mt-1 text-xs font-medium text-oe-blue hover:underline"
              onClick={() => setOpen(true)}
            >
              {hasNote
                ? t('cost_control.note_edit', { defaultValue: 'Edit the reason' })
                : t('cost_control.note_add', { defaultValue: 'Add a reason' })}
            </button>
          )}
          {editable && open && (
            <NoteEditor
              projectId={projectId}
              snapshotId={detail.id}
              line={line}
              onSaved={() => {
                setOpen(false);
                onSaved();
              }}
            />
          )}
        </div>
      </div>
    </li>
  );
}

export interface SnapshotDrawerProps {
  projectId: string;
  snapshotId: string | null;
  currency: string;
  canEdit: boolean;
  onClose: () => void;
}

export function SnapshotDrawer({ projectId, snapshotId, currency, canEdit, onClose }: SnapshotDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [filter, setFilter] = useState<'attention' | 'moved' | 'all'>('attention');

  const detail = useQuery({
    queryKey: ['cost-control', 'snapshot', snapshotId],
    queryFn: () => costControlApi.snapshot(snapshotId!),
    enabled: !!snapshotId,
  });
  const reload = () => queryClient.invalidateQueries({ queryKey: ['cost-control'] });

  const refresh = useMutation({
    mutationFn: () => costControlApi.refreshSnapshot(snapshotId!),
    onSuccess: () => {
      reload();
      addToast({ type: 'success', title: t('cost_control.draft_refreshed', { defaultValue: "Today's figures taken in" }) });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.draft_refresh_failed', { defaultValue: 'Could not update the draft' }),
        message: getErrorMessage(err),
      }),
  });
  const freeze = useMutation({
    mutationFn: () => costControlApi.freezeSnapshot(snapshotId!),
    onSuccess: () => {
      reload();
      addToast({ type: 'success', title: t('cost_control.draft_frozen', { defaultValue: 'Snapshot frozen' }) });
    },
    onError: (err: unknown) => {
      reload();
      addToast({
        type: 'error',
        title: t('cost_control.draft_freeze_failed', { defaultValue: 'Not frozen yet' }),
        message: getErrorMessage(err),
      });
    },
  });

  const data = detail.data;
  const isDraft = data?.status === 'draft';
  const editable = isDraft && canEdit;
  const missing = useMemo(() => (data?.lines ?? []).filter((l) => l.needs_evidence && !l.documented), [data]);
  const effectiveFilter = filter === 'attention' && isDraft && missing.length === 0 ? 'moved' : filter;
  const lines = useMemo(() => {
    const all = data?.lines ?? [];
    if (effectiveFilter === 'all') return all;
    if (effectiveFilter === 'attention' && isDraft) return all.filter((l) => l.needs_evidence);
    return all.filter((l) => (l.previous === null && !!data?.previous) || Math.abs(num(l.delta)) >= 0.005 || !!l.comment);
  }, [data, effectiveFilter, isDraft]);

  return (
    <SideDrawer
      open={!!snapshotId}
      onClose={onClose}
      title={
        data
          ? `${data.label || stageLabel(t, data.stage)} · ${fmtDate(data.taken_on)}`
          : t('cost_control.snapshot_title', { defaultValue: 'Snapshot' })
      }
      subtitle={data ? snapshotStatusLabel(t, data.status) : undefined}
      widthClass="max-w-2xl sm:min-w-[40rem]"
    >
      {detail.isLoading ? (
        <Skeleton className="m-5 h-64" />
      ) : detail.error || !data ? (
        <p className="p-5 text-sm text-semantic-error">{getErrorMessage(detail.error)}</p>
      ) : (
        <div className="space-y-5 p-5">
          <section className="rounded-xl border border-border-light p-4 text-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t('cost_control.col_forecast', { defaultValue: 'Forecast' })}
                </div>
                <div className="text-2xl font-bold tabular-nums text-content-primary">
                  {fmtCurrency(data.totals.forecast, currency)}
                </div>
                {data.previous && (
                  <div className="text-xs text-content-tertiary">
                    {t('cost_control.snapshot_previous', {
                      defaultValue: 'Last frozen on {{date}}: {{amount}}',
                      date: fmtDate(data.previous.taken_on),
                      amount: fmtCurrency(data.previous.totals.forecast, currency),
                    })}
                  </div>
                )}
              </div>
              <span
                className={`flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
                  isDraft
                    ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
                    : 'bg-surface-secondary text-content-secondary'
                }`}
              >
                {!isDraft && <Lock size={12} />}
                {snapshotStatusLabel(t, data.status)}
              </span>
            </div>
            <p className="mt-2 text-xs text-content-secondary">
              {isDraft
                ? data.previous
                  ? t('cost_control.draft_explain', {
                      defaultValue:
                        'This draft is still open. Lines that moved above the threshold need a reason before it can be frozen. Once frozen it is a record and cannot be changed.',
                    })
                  : t('cost_control.draft_baseline', {
                      defaultValue:
                        'This is the first snapshot of the project, the baseline every later one is compared with. Nothing needs a reason yet.',
                    })
                : t('cost_control.frozen_explain', {
                    defaultValue: 'Frozen on {{date}}. A frozen snapshot is a record and cannot be changed or deleted.',
                    date: data.frozen_at ? fmtDate(data.frozen_at) : fmtDate(data.taken_on),
                  })}
            </p>
            <p className="mt-1 text-xs text-content-tertiary">
              {t('cost_control.snapshot_method', {
                defaultValue: 'Method: {{method}}',
                method: methodLabel(t, data.forecast_method),
              })}
            </p>
            {editable && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Lock size={14} />}
                  onClick={() => freeze.mutate()}
                  disabled={freeze.isPending || missing.length > 0}
                >
                  {t('cost_control.draft_freeze', { defaultValue: 'Freeze snapshot' })}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<RefreshCw size={14} />}
                  onClick={() => refresh.mutate()}
                  disabled={refresh.isPending}
                >
                  {t('cost_control.draft_refresh', { defaultValue: "Take in today's figures" })}
                </Button>
                {missing.length > 0 && (
                  <span className="text-xs text-amber-700 dark:text-amber-300">
                    {t('cost_control.draft_missing', {
                      defaultValue: 'Lines still waiting for a reason: {{n}}',
                      n: missing.length,
                    })}
                  </span>
                )}
              </div>
            )}
          </section>

          <section>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="me-auto text-sm font-semibold text-content-primary">
                {t('cost_control.snapshot_lines', { defaultValue: 'Lines' })}
              </h3>
              {(isDraft ? (['attention', 'moved', 'all'] as const) : (['moved', 'all'] as const)).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFilter(f)}
                  className={`rounded-full px-2.5 py-0.5 text-xs ${
                    effectiveFilter === f
                      ? 'bg-oe-blue text-white'
                      : 'bg-surface-secondary text-content-secondary hover:text-content-primary'
                  }`}
                >
                  {f === 'attention'
                    ? t('cost_control.filter_attention', { defaultValue: 'Need a reason' })
                    : f === 'moved'
                      ? t('cost_control.filter_moved', { defaultValue: 'Moved' })
                      : t('cost_control.filter_all', { defaultValue: 'All lines' })}
                </button>
              ))}
            </div>
            {lines.length === 0 ? (
              <p className="text-sm text-content-tertiary">
                {t('cost_control.snapshot_nothing_moved', {
                  defaultValue: 'No line moved since the last frozen snapshot.',
                })}
              </p>
            ) : (
              <ul className="divide-y divide-border-light">
                {lines.map((line) => (
                  <LineCard
                    key={line.key}
                    projectId={projectId}
                    detail={data}
                    line={line}
                    currency={currency}
                    editable={editable}
                    onSaved={reload}
                  />
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </SideDrawer>
  );
}
