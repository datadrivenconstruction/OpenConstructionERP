// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Commissioning stages: the steps every system passes through, from factory
// test to proof of operation, and where each system stands on each of them.
// A stage is tested here but released elsewhere: asking for a release opens a
// hold point in construction control, and the party named for the stage
// releases it there. That is why this screen has no release button.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Check, Layers, Minus, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  addStage,
  applyCatalogueStages,
  deleteStage,
  reinstateStage,
  markStageNotApplicable,
  openStageTest,
  patchStage,
  recordStageResult,
  requestStageRelease,
  setStageDependencies,
  syncStageProgress,
  type CxSystemRef,
  type ReleaseRequestResult,
  type StageDef,
  type StageProgress,
} from './api';
import { EvidenceLinks } from './EvidenceLinks';
import { ExportButtons } from './ExportButtons';
import { useQcWrite, useStageMatrix } from './hooks';
import { ClosedReasons, SharedReasons } from './ClosedReasons';
import {
  PARTY_ROLE,
  PRECONDITION,
  PRECONDITION_REASON,
  SEVERITY,
  STAGE_ACTION,
  STAGE_STATE,
  nameIn,
  gate,
  vocab,
  type TFn,
} from './labels';
import type { PanelProps } from './panel';
import { Field, FormDialog, Hint, RefusalNote, STAGE_TONE, Section, StateBadge, VocabSelect, inputCls } from './QualityBits';
import {
  PLAN_STAGE_ACTIONS,
  STAGE_ACTIONS,
  planRowActions,
  preconditionNotApplicable,
  sharedReasons,
  type StageAction,
} from './rules';

const PARTIES = ['qc', 'qa', 'tpi', 'ahj'] as const;
const SEVERITIES = ['low', 'medium', 'high', 'critical'] as const;

type Dialog =
  | { kind: 'stage'; stage: StageDef | null }
  | { kind: 'result'; progress: StageProgress; result: 'pass' | 'fail' }
  | { kind: 'na'; progress: StageProgress }
  | { kind: 'depends'; progress: StageProgress }
  | null;

export function StagesPanel(props: PanelProps) {
  const { projectId, catalogue, labels, personName, editable, manage } = props;
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const matrix = useStageMatrix(projectId);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [removing, setRemoving] = useState<StageDef | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [released, setReleased] = useState<ReleaseRequestResult | null>(null);

  if (matrix.isLoading) return <SkeletonTable rows={6} columns={6} />;
  if (matrix.isError) {
    return (
      <ErrorState
        title={t('qualityConcept.stages.load_failed', { defaultValue: 'The commissioning stages could not be loaded' })}
        hint={getErrorMessage(matrix.error)}
        onRetry={() => matrix.refetch()}
      />
    );
  }
  const stages = matrix.data?.stages ?? [];
  const systems = matrix.data?.systems ?? [];
  const progress = matrix.data?.items ?? [];
  const stageName = (s: StageDef) => s.name_override || nameIn(labels, catalogue?.commissioning_stages, s.catalogue_code || s.code);
  const stageNameByCode = (code: string) => {
    const s = stages.find((x) => x.code === code);
    return s ? stageName(s) : nameIn(labels, catalogue?.commissioning_stages, code);
  };
  const cell = (systemId: string, stageCode: string) =>
    progress.find((p) => p.system_id === systemId && p.stage_code === stageCode) ?? null;
  const current = selected ? (progress.find((p) => p.id === selected) ?? null) : null;
  const currentSystem = current ? (systems.find((s) => s.id === current.system_id) ?? null) : null;

  const run = (row: StageProgress, action: StageAction) => {
    setReleased(null);
    if (action === 'pass' || action === 'fail') setDialog({ kind: 'result', progress: row, result: action });
    else if (action === 'not_applicable') setDialog({ kind: 'na', progress: row });
    else if (action === 'open_test') write.send(() => openStageTest(projectId, row.id));
    else if (action === 'reinstate') write.send(() => reinstateStage(projectId, row.id));
    else write.send(() => requestStageRelease(projectId, row.id), setReleased);
  };

  if (stages.length === 0) {
    return (
      <div className="space-y-4" data-testid="stages-panel">
        <RefusalNote refusal={write.refusal} />
        <EmptyState
          icon={<Layers size={28} />}
          title={t('qualityConcept.stages.empty_title', { defaultValue: 'No commissioning stages yet' })}
          description={t('qualityConcept.stages.empty_body', {
            defaultValue:
              'Stages are the steps every technical system passes before handover, from the factory test to the proof of operation. Start from the stages the catalogue proposes and adjust them to the project.',
          })}
          action={
            editable
              ? {
                  label: t('qualityConcept.stages.apply', { defaultValue: 'Use the catalogue stages' }),
                  onClick: () => write.send(() => applyCatalogueStages(projectId)),
                }
              : undefined
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="stages-panel">
      <RefusalNote refusal={write.refusal} violations={write.violations} />
      {released && (
        <div role="status" data-testid="release-requested" className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-primary">
          {t('qualityConcept.stages.release_requested', {
            defaultValue: 'A hold point was opened. It is released in construction control by: {{party}}.',
            party: vocab(t as TFn, PARTY_ROLE, released.hold_gate.required_party_role),
          })}{' '}
          <Link className="text-oe-blue-text underline" to={`/projects/${projectId}/construction-control`}>
            {t('qualityConcept.stages.open_construction_control', { defaultValue: 'Open construction control' })}
          </Link>
        </div>
      )}

      <Section
        testId="stage-model"
        title={t('qualityConcept.stages.model_title', { defaultValue: 'Stages of this project' })}
        description={t('qualityConcept.stages.model_body', {
          defaultValue: 'Each stage needs an owner who runs it and a party who releases it.',
        })}
        action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" disabled={!editable} loading={write.pending} onClick={() => write.send(() => applyCatalogueStages(projectId))} data-testid="stages-apply">
              {t('qualityConcept.stages.apply_missing', { defaultValue: 'Add missing catalogue stages' })}
            </Button>
            <Button size="sm" variant="secondary" icon={<Plus size={14} />} disabled={!editable} onClick={() => setDialog({ kind: 'stage', stage: null })} data-testid="stage-add">
              {t('qualityConcept.stages.add', { defaultValue: 'Add stage' })}
            </Button>
          </div>
        }
      >
        <SharedReasons codes={sharedReasons(stages, planRowActions)} />
        <ol className="divide-y divide-border-light" data-testid="stage-list">
          {stages.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-2 py-2 text-sm" data-testid="stage-entry">
              <span className="w-6 text-right text-content-tertiary">{s.order}</span>
              <span className="font-medium text-content-primary">{stageName(s)}</span>
              <span className={clsx('text-xs', s.owner_user_id ? 'text-content-secondary' : 'text-semantic-error')} data-testid="stage-owner">
                {s.owner_user_id
                  ? t('qualityConcept.stages.owner_line', {
                      defaultValue: 'Owner: {{name}}',
                      name: s.owner_user_id_name ?? personName(s.owner_user_id) ?? t('qualityConcept.common.member', { defaultValue: 'Project member' }),
                    })
                  : t('qualityConcept.stages.owner_missing', { defaultValue: 'No owner yet' })}
              </span>
              <span className="text-xs text-content-secondary">
                {t('qualityConcept.stages.release_line', {
                  defaultValue: 'Released by: {{party}}',
                  party: vocab(t as TFn, PARTY_ROLE, s.release_party_role),
                })}
              </span>
              {s.evidence_types.length > 0 && (
                <span className="min-w-0 flex-1 truncate text-xs text-content-tertiary">
                  {fmtList(s.evidence_types.map((e) => nameIn(labels, catalogue?.evidence_types, e)))}
                </span>
              )}
              <span className="ml-auto flex gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  {...gate(t as TFn, s, 'edit', editable)}
                  icon={<Pencil size={14} />}
                  aria-label={t('qualityConcept.common.edit', { defaultValue: 'Edit' })}
                  onClick={() => setDialog({ kind: 'stage', stage: s })}
                  data-testid="stage-edit"
                />
                <Button
                  size="sm"
                  variant="ghost"
                  {...gate(t as TFn, s, 'delete', editable)}
                  icon={<Trash2 size={14} />}
                  aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
                  onClick={() => setRemoving(s)}
                />
              </span>
              <ClosedReasons row={s} actions={planRowActions()} skip={sharedReasons(stages, planRowActions)} />
            </li>
          ))}
        </ol>
      </Section>

      <Section
        testId="stage-matrix"
        title={t('qualityConcept.stages.matrix_title', { defaultValue: 'Systems and their stages' })}
        description={t('qualityConcept.stages.matrix_body', {
          defaultValue: 'One row per technical system. Pick a cell to see what it waits for and to record a test.',
        })}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <ExportButtons
              projectId={projectId}
              what="stages"
              label={t('qualityConcept.export.stage_list', { defaultValue: 'Stage list' })}
            />
            <ExportButtons
              projectId={projectId}
              what="stage_matrix"
              label={t('qualityConcept.export.stage_matrix', { defaultValue: 'Stage matrix' })}
            />
            <Button size="sm" variant="secondary" icon={<RefreshCw size={14} />} loading={write.pending} onClick={() => write.send(() => syncStageProgress(projectId))} data-testid="stages-sync">
              {t('qualityConcept.stages.sync', { defaultValue: 'Update from commissioning' })}
            </Button>
          </div>
        }
      >
        {systems.length === 0 ? (
          <Hint testId="matrix-no-systems">
            {t('qualityConcept.stages.no_systems', {
              defaultValue:
                'No technical systems yet. Systems are kept in Commissioning: add them there, then update this page.',
            })}{' '}
            <Link className="text-oe-blue-text underline" to="/commissioning">
              {t('qualityConcept.stages.open_commissioning', { defaultValue: 'Open Commissioning' })}
            </Link>
          </Hint>
        ) : progress.length === 0 ? (
          <Hint testId="matrix-not-synced">
            {t('qualityConcept.stages.not_synced', {
              defaultValue: 'The systems are not laid out against the stages yet. Press Update from commissioning.',
            })}
          </Hint>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
            <table className="w-full min-w-[640px] text-sm" data-testid="matrix-table">
              <thead>
                <tr className="text-left text-xs text-content-tertiary">
                  <th className="py-1 pr-3 font-medium">{t('qualityConcept.stages.system', { defaultValue: 'System' })}</th>
                  {stages.map((s) => (
                    <th key={s.id} className="px-1 py-1 font-medium">
                      {stageName(s)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {systems.map((sys) => (
                  <tr key={sys.id} className="border-t border-border-light">
                    <th scope="row" className="py-1.5 pr-3 text-left font-medium text-content-primary">
                      {sys.name}
                    </th>
                    {stages.map((s) => {
                      const p = cell(sys.id, s.code);
                      return (
                        <td key={s.id} className="px-1 py-1.5">
                          {p ? (
                            <button
                              type="button"
                              aria-pressed={selected === p.id}
                              aria-label={t('qualityConcept.stages.cell_label', {
                                defaultValue: '{{system}}, {{stage}}: {{state}}',
                                system: sys.name,
                                stage: stageName(s),
                                state: vocab(t as TFn, STAGE_STATE, p.computed_state),
                              })}
                              onClick={() => setSelected(selected === p.id ? null : p.id)}
                              className={clsx('rounded-md p-0.5', selected === p.id && 'ring-2 ring-oe-blue')}
                              data-testid="matrix-cell"
                            >
                              <StateBadge map={STAGE_STATE} tones={STAGE_TONE} code={p.computed_state} />
                            </button>
                          ) : (
                            <span className="text-content-quaternary">-</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {current && (
        <Section
          testId="stage-detail"
          title={t('qualityConcept.stages.detail_title', {
            defaultValue: '{{system}}: {{stage}}',
            system: currentSystem?.name ?? '',
            stage: stageNameByCode(current.stage_code),
          })}
          action={<StateBadge map={STAGE_STATE} tones={STAGE_TONE} code={current.computed_state} testId="stage-detail-state" />}
        >
          <ul className="space-y-1" data-testid="precondition-list">
            {current.preconditions.map((pre, i) => (
              <li
                key={`${pre.code}:${i}`}
                className="flex items-start gap-1.5 text-sm"
                data-testid="precondition"
                data-met={preconditionNotApplicable(pre) ? 'not-applicable' : pre.met}
              >
                {preconditionNotApplicable(pre) ? (
                  <Minus size={14} className="mt-0.5 shrink-0 text-content-tertiary" aria-hidden />
                ) : pre.met ? (
                  <Check size={14} className="mt-0.5 shrink-0 text-semantic-success" aria-hidden />
                ) : (
                  <X size={14} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
                )}
                <span className="text-content-primary">{vocab(t as TFn, PRECONDITION, pre.code)}</span>
                {preconditionNotApplicable(pre) && (
                  <span className="text-content-secondary">
                    {t('qualityConcept.stages.precondition_not_applicable', { defaultValue: 'Not applicable' })}
                  </span>
                )}
                {(!pre.met || preconditionNotApplicable(pre)) && pre.reason && (
                  <span className="text-content-secondary">{vocab(t as TFn, PRECONDITION_REASON, pre.reason)}</span>
                )}
              </li>
            ))}
          </ul>
          {current.rationale && <p className="mt-2 text-sm text-content-secondary">{current.rationale}</p>}
          {current.released_at && (
            <p className="mt-2 text-sm text-content-secondary" data-testid="stage-released">
              {(current.released_by_name ?? personName(current.released_by))
                ? t('qualityConcept.stages.released_on_by', {
                    defaultValue: 'Released on {{date}} by {{name}}',
                    date: fmtDate(current.released_at),
                    name: current.released_by_name ?? personName(current.released_by),
                  })
                : t('qualityConcept.stages.released_on', { defaultValue: 'Released on {{date}}', date: fmtDate(current.released_at) })}
            </p>
          )}
          {current.hold_gate_id && current.computed_state !== 'released' && (
            <p className="mt-2 text-sm text-content-secondary" data-testid="release-pending">
              {current.hold_gate?.label
                ? t('qualityConcept.stages.release_pending_gate', {
                    defaultValue: 'Hold point {{gate}} is open for this stage. It is released in construction control.',
                    gate: current.hold_gate.label,
                  })
                : t('qualityConcept.stages.release_pending', {
                    defaultValue: 'A hold point is open for this stage. It is released in construction control.',
                  })}{' '}
              <Link className="text-oe-blue-text underline" to={`/projects/${projectId}/construction-control`}>
                {t('qualityConcept.stages.open_construction_control', { defaultValue: 'Open construction control' })}
              </Link>
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {(STAGE_ACTIONS[current.computed_state] ?? []).map((action) => (
              <Button
                key={action}
                size="sm"
                variant={action === 'not_applicable' ? 'ghost' : 'secondary'}
                loading={write.pending}
                {...gate(t as TFn, current, action, manage || !PLAN_STAGE_ACTIONS.has(action))}
                onClick={() => run(current, action)}
                data-testid={`stage-action-${action}`}
              >
                {vocab(t as TFn, STAGE_ACTION, action)}
              </Button>
            ))}
            <Button size="sm" variant="ghost" {...gate(t as TFn, current, 'set_dependencies', manage)} onClick={() => setDialog({ kind: 'depends', progress: current })} data-testid="stage-depends">
              {t('qualityConcept.stages.depends', { defaultValue: 'Systems it depends on' })}
            </Button>
            <ClosedReasons row={current} actions={['set_dependencies', ...(STAGE_ACTIONS[current.computed_state] ?? [])]} />
          </div>
          <div className="mt-3">
            <EvidenceLinks projectId={projectId} ownerKind="stage_progress" ownerId={current.id} row={current} />
          </div>
        </Section>
      )}

      {dialog?.kind === 'stage' && <StageDialog {...props} stage={dialog.stage} nextOrder={stages.length} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'result' && (
        <ResultDialog {...props} progress={dialog.progress} result={dialog.result} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === 'na' && <NotApplicableDialog {...props} progress={dialog.progress} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'depends' && (
        <DependsDialog {...props} progress={dialog.progress} systems={systems} onClose={() => setDialog(null)} />
      )}
      <ConfirmDialog
        open={!!removing}
        variant="danger"
        loading={write.pending}
        title={t('qualityConcept.stages.remove_title', { defaultValue: 'Remove this stage?' })}
        message={t('qualityConcept.stages.remove_body', {
          defaultValue: 'The stage is taken out of the project. A stage that systems already ran through cannot be removed.',
        })}
        confirmLabel={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
        cancelLabel={t('qualityConcept.common.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const row = removing;
          setRemoving(null);
          if (row) write.send(() => deleteStage(projectId, row.id));
        }}
      />
    </div>
  );
}

function StageDialog({
  projectId,
  personName,
  stage,
  nextOrder,
  onClose,
}: PanelProps & { stage: StageDef | null; nextOrder: number; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [code, setCode] = useState('');
  const [name, setName] = useState(stage?.name_override ?? '');
  const [order, setOrder] = useState(String(stage?.order ?? nextOrder));
  const [owner, setOwner] = useState(stage?.owner_user_id ?? '');
  const [ownerName, setOwnerName] = useState(personName(stage?.owner_user_id) ?? '');
  const [party, setParty] = useState(stage?.release_party_role ?? 'qa');
  const orderNo = /^\d+$/.test(order.trim()) ? Number(order.trim()) : null;
  const problem =
    !stage && !/^[a-z0-9][a-z0-9_]*$/.test(code.trim())
      ? t('qualityConcept.stages.problem_code', {
          defaultValue: 'Give the stage a short code in lower case letters, digits and underscores',
        })
      : orderNo === null
        ? t('qualityConcept.stages.problem_order', { defaultValue: 'Enter the position as a whole number' })
        : null;

  return (
    <FormDialog
      open
      testId="stage-dialog"
      title={
        stage
          ? t('qualityConcept.stages.edit_title', { defaultValue: 'Edit stage' })
          : t('qualityConcept.stages.add', { defaultValue: 'Add stage' })
      }
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={problem}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(
          () =>
            stage
              ? patchStage(projectId, stage.id, {
                  order: orderNo ?? 0,
                  name_override: name.trim(),
                  owner_user_id: owner || null,
                  release_party_role: party,
                })
              : addStage(projectId, {
                  code: code.trim(),
                  order: orderNo ?? 0,
                  name_override: name.trim(),
                  owner_user_id: owner || null,
                  release_party_role: party,
                }),
          onClose,
        )
      }
    >
      <div className="grid gap-3 md:grid-cols-2">
        {!stage && (
          <Field required label={t('qualityConcept.stages.code', { defaultValue: 'Code' })}>
            <input className={inputCls} value={code} onChange={(e) => setCode(e.target.value)} data-testid="stage-code" />
          </Field>
        )}
        <Field
          label={t('qualityConcept.stages.name', { defaultValue: 'Name in this project' })}
          hint={stage ? t('qualityConcept.stages.name_hint', { defaultValue: 'Leave empty to keep the catalogue name.' }) : undefined}
        >
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field required label={t('qualityConcept.stages.order', { defaultValue: 'Position' })}>
          <input className={inputCls} inputMode="numeric" value={order} onChange={(e) => setOrder(e.target.value)} />
        </Field>
        <Field label={t('qualityConcept.stages.owner', { defaultValue: 'Owner' })}>
          <ProjectPeopleSelect
            projectId={projectId}
            value={owner}
            displayValue={ownerName}
            onChange={(id, display) => {
              setOwner(id);
              setOwnerName(display);
            }}
          />
        </Field>
        <Field required label={t('qualityConcept.stages.release_party', { defaultValue: 'Who releases it' })}>
          <VocabSelect map={PARTY_ROLE} codes={PARTIES} value={party} onChange={setParty} testId="stage-party" />
        </Field>
      </div>
    </FormDialog>
  );
}

function ResultDialog({
  projectId,
  progress,
  result,
  onClose,
}: PanelProps & { progress: StageProgress; result: 'pass' | 'fail'; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [note, setNote] = useState('');
  const [severity, setSeverity] = useState<(typeof SEVERITIES)[number]>('high');

  return (
    <FormDialog
      open
      size="sm"
      testId="stage-result-dialog"
      title={vocab(t as TFn, STAGE_ACTION, result)}
      subtitle={
        result === 'pass'
          ? t('qualityConcept.stages.pass_hint', {
              defaultValue: 'A pass needs passing evidence linked to this stage first.',
            })
          : t('qualityConcept.stages.fail_hint', {
              defaultValue: 'A fail opens a commissioning issue with the severity you choose.',
            })
      }
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      submitLabel={vocab(t as TFn, STAGE_ACTION, result)}
      onSubmit={() =>
        write.send(() => recordStageResult(projectId, progress.id, { result, note: note.trim(), severity }), onClose)
      }
    >
      {result === 'fail' && (
        <Field label={t('qualityConcept.stages.severity', { defaultValue: 'How serious' })}>
          <VocabSelect map={SEVERITY} codes={SEVERITIES} value={severity} onChange={(v) => setSeverity(v as typeof severity)} />
        </Field>
      )}
      <Field label={t('qualityConcept.common.note', { defaultValue: 'Note' })}>
        <textarea rows={3} className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} data-testid="stage-result-note" />
      </Field>
    </FormDialog>
  );
}

function NotApplicableDialog({ projectId, progress, onClose }: PanelProps & { progress: StageProgress; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [reason, setReason] = useState('');

  return (
    <FormDialog
      open
      size="sm"
      testId="stage-na-dialog"
      title={vocab(t as TFn, STAGE_ACTION, 'not_applicable')}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={reason.trim() ? null : t('qualityConcept.common.problem_reason', { defaultValue: 'Write down the reason' })}
      submitLabel={vocab(t as TFn, STAGE_ACTION, 'not_applicable')}
      onSubmit={() => write.send(() => markStageNotApplicable(projectId, progress.id, reason.trim()), onClose)}
    >
      <Field required label={t('qualityConcept.common.reason', { defaultValue: 'Reason' })}>
        <textarea rows={3} className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="stage-na-reason" />
      </Field>
    </FormDialog>
  );
}

function DependsDialog({
  projectId,
  progress,
  systems,
  onClose,
}: PanelProps & { progress: StageProgress; systems: CxSystemRef[]; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [ids, setIds] = useState<string[]>(progress.depends_on_system_ids);
  const others = systems.filter((s) => s.id !== progress.system_id);

  return (
    <FormDialog
      open
      size="sm"
      testId="stage-depends-dialog"
      title={t('qualityConcept.stages.depends', { defaultValue: 'Systems it depends on' })}
      subtitle={t('qualityConcept.stages.depends_body', {
        defaultValue: 'If one of these systems is tested again, the release of this stage is marked as outdated.',
      })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() => write.send(() => setStageDependencies(projectId, progress.id, ids), onClose)}
    >
      {others.length === 0 ? (
        <Hint>{t('qualityConcept.stages.depends_none', { defaultValue: 'There is no other system in the project.' })}</Hint>
      ) : (
        <div className="space-y-1">
          {others.map((s) => (
            <label key={s.id} className="flex items-center gap-2 text-sm text-content-primary">
              <input
                type="checkbox"
                checked={ids.includes(s.id)}
                onChange={(e) => setIds(e.target.checked ? [...ids, s.id] : ids.filter((x) => x !== s.id))}
              />
              {s.name}
            </label>
          ))}
        </div>
      )}
    </FormDialog>
  );
}
