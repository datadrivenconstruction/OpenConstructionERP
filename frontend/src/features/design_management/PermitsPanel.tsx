// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The permit design package: the drawings, reports and forms that go to the
// authority. Each item shows whether its document exists and is shared, so
// what still blocks the submission is visible at a glance. After submission
// the state follows the authority review. Conditions the authority attaches
// to an approval are recorded as proposals and become tasks only when a
// person confirms each one.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, CircleAlert, Landmark } from 'lucide-react';

import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { fmtDate } from '@/shared/lib/formatters';
import { useConfirm } from '@/shared/hooks/useConfirm';

import {
  addPermitItem,
  createPermit,
  decidePermitCondition,
  listPermits,
  listReports,
  movePermit,
  proposePermitConditions,
  removePermitItem,
  syncPermit,
  updatePermit,
  type Permit,
  type PermitInput,
  type PermitItem,
  type PermitItemKind,
} from './api';
import { ListState, PERMIT_TONE, PanelHeader, StepButton, ToneBadge, hasRows, pickerField, type DesignContext, WriteButton } from './DesignBits';
import { FormDialog, flag, str, type FieldSpec, type FormValues } from './FormDialog';
import { useDesignAction, useDesignList, useDesignOptions } from './hooks';
import { CONDITION_STATE, PERMIT_ITEM, PERMIT_STATE, permitProfileName, reportKindName, ui, uiCount, vocab, vocabOptions, type TFn } from './labels';
import { STEP_LABEL, changedFields, filledFields, offered } from './rules';

type Dialog =
  | { kind: 'permit'; permit: Permit | null }
  | { kind: 'item'; permit: Permit }
  | { kind: 'condition'; permit: Permit }
  | null;

function permitValues(permit: Permit | null): FormValues {
  return {
    title: permit?.title ?? '',
    profile_code: permit?.profile_code ?? '',
    target_submission_date: permit?.target_submission_date ?? '',
    authority_submission_id: permit?.authority_submission_id ?? '',
    review_cycle_id: permit?.review_cycle_id ?? '',
    code: permit?.code ?? '',
  };
}

function itemState(item: PermitItem): 'ready' | 'not_shared' | 'missing' {
  if (item.state_ok) return 'ready';
  return item.present ? 'not_shared' : 'missing';
}

export function PermitsPanel({ ctx }: { ctx: DesignContext }) {
  const { t: rawT } = useTranslation();
  const t = rawT as TFn;
  const [dialog, setDialog] = useState<Dialog>(null);
  const action = useDesignAction(ctx.onChanged);
  const confirmState = useConfirm();
  const permits = useDesignList(ctx.projectId, 'permits', listPermits);
  const reports = useDesignList(ctx.projectId, 'reports', listReports);
  const submissions = useDesignOptions(ctx.projectId, 'authority_submissions', ctx.labels);
  const cycles = useDesignOptions(ctx.projectId, 'review_cycles', ctx.labels);
  const catalogue = ctx.setup.reports_catalogue;
  const profileName = (code: string) => permitProfileName(ctx.labels, catalogue, code);

  const permitFields = (editing: boolean): FieldSpec[] => [
    { name: 'title', label: ui(t, 'design.ui.field.title'), type: 'text', required: true },
    ...(editing
      ? []
      : [
          {
            name: 'profile_code',
            label: ui(t, 'design.ui.permit.profile'),
            type: 'select' as const,
            required: true,
            options: catalogue.permit_steps.map((p) => ({ value: p.code, label: profileName(p.code) })),
            hint: ui(t, 'design.ui.permit.profile_hint'),
          },
        ]),
    { name: 'target_submission_date', label: ui(t, 'design.ui.permit.target_date'), type: 'date' },
    ...pickerField('authority_submission_id', ui(t, 'design.ui.permit.authority_submission'), submissions),
    ...pickerField('review_cycle_id', ui(t, 'design.ui.permit.review_cycle'), cycles),
    { name: 'code', label: ui(t, 'design.ui.field.code'), type: 'text', hint: ui(t, 'design.ui.field.code_hint') },
  ];
  const itemFields: FieldSpec[] = [
    { name: 'kind', label: ui(t, 'design.ui.permit.item_kind'), type: 'select', required: true, options: vocabOptions(t, PERMIT_ITEM) },
    {
      name: 'container_id',
      label: ui(t, 'design.ui.permit.item_drawing'),
      type: 'select',
      required: true,
      showIf: (v) => str(v, 'kind') === 'drawing',
      options: ctx.drawings.map((d) => ({ value: d.container_id, label: `${d.number} ${d.title}` })),
    },
    {
      name: 'report_id',
      label: ui(t, 'design.ui.permit.item_report'),
      type: 'select',
      required: true,
      showIf: (v) => str(v, 'kind') === 'report',
      options: (reports.data ?? []).map((r) => ({
        value: r.id,
        label: `${r.code} ${reportKindName(ctx.labels, catalogue, r.kind_code)}`,
      })),
    },
    { name: 'title', label: ui(t, 'design.ui.field.title'), type: 'text', required: true, showIf: (v) => str(v, 'kind') === 'form' },
    { name: 'required', label: ui(t, 'design.ui.permit.item_required'), type: 'checkbox' },
  ];

  const itemBody = (values: FormValues) => {
    const kind = str(values, 'kind') as PermitItemKind;
    const drawing = ctx.drawings.find((d) => d.container_id === str(values, 'container_id'));
    const report = (reports.data ?? []).find((r) => r.id === str(values, 'report_id'));
    if (kind === 'drawing') {
      return { kind, title: drawing?.title ?? '', container_id: drawing?.container_id ?? null, required: flag(values, 'required') };
    }
    if (kind === 'report') {
      return {
        kind,
        title: report ? report.title || reportKindName(ctx.labels, catalogue, report.kind_code) : '',
        report_id: report?.id ?? null,
        container_id: report?.container_id ?? null,
        required: flag(values, 'required'),
      };
    }
    return { kind, title: str(values, 'title'), required: flag(values, 'required') };
  };
  const add = () => setDialog({ kind: 'permit', permit: null });

  return (
    <div className="space-y-4" data-testid="design-permit-panel">
      <ConfirmDialog {...confirmState} />
      <PanelHeader
        title={ui(t, 'design.ui.permit.title')}
        hint={ui(t, 'design.ui.permit.hint')}
        action={
          <WriteButton onClick={add} data-testid="permit-add">
            {ui(t, 'design.ui.permit.add')}
          </WriteButton>
        }
      />
      <ListState
        query={permits}
        failedKey="design.ui.permit.load_failed"
        emptyIcon={<Landmark size={28} />}
        emptyTitle={ui(t, 'design.ui.permit.empty_title')}
        emptyBody={ui(t, 'design.ui.permit.empty_body')}
        emptyAction={{ label: ui(t, 'design.ui.permit.add'), onClick: add }}
      />
      {hasRows(permits) &&
        (permits.data ?? []).map((permit) => {
          const assembling = permit.state === 'assembling';
          const approved = permit.state === 'approved' || permit.state === 'partially_approved';
          return (
            <section key={permit.id} className="space-y-3 rounded-lg border border-border-light p-4" data-testid="permit-card">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-content-tertiary">{permit.code}</span>
                <h3 className="font-medium text-content-primary">{permit.title}</h3>
                <ToneBadge tone={PERMIT_TONE[permit.state]} testId="permit-state">
                  {vocab(t, PERMIT_STATE, permit.state)}
                </ToneBadge>
                <span className="text-xs text-content-secondary">{profileName(permit.profile_code)}</span>
                {permit.target_submission_date && (
                  <span className="text-xs text-content-secondary">
                    {ui(t, 'design.ui.permit.target_shown', { date: fmtDate(permit.target_submission_date) })}
                  </span>
                )}
                <span className="ml-auto flex flex-wrap gap-1">
                  {assembling && (
                    <WriteButton size="sm" variant="ghost" onClick={() => setDialog({ kind: 'permit', permit })}>
                      {ui(t, 'design.ui.action.edit')}
                    </WriteButton>
                  )}
                  {permit.review_cycle_id && (
                    <WriteButton size="sm" variant="ghost" disabled={action.pending} onClick={() => action.run(() => syncPermit(ctx.projectId, permit.id))} data-testid="permit-sync">
                      {ui(t, 'design.ui.permit.sync')}
                    </WriteButton>
                  )}
                  {offered(permit.can?.transitions).map(({ target, flag }) => (
                    <StepButton
                      key={target}
                      flag={flag}
                      label={ui(t, STEP_LABEL.permit[target])}
                      variant={target === 'ready' || target === 'submitted' ? 'secondary' : 'ghost'}
                      busy={action.pending}
                      onClick={() => action.run(() => movePermit(ctx.projectId, permit.id, target))}
                      testId={`permit-to-${target}`}
                    />
                  ))}
                </span>
              </div>

              {permit.superseded_content && (
                <p role="status" className="rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm text-content-primary" data-testid="permit-superseded">
                  {ui(t, 'design.ui.permit.superseded')}
                </p>
              )}
              {assembling && permit.missing.length > 0 && (
                <p className="text-sm text-semantic-warning" data-testid="permit-missing">
                  {uiCount(t, 'design.ui.permit.missing', permit.missing.length)}
                </p>
              )}

              {permit.items.length === 0 ? (
                <p className="text-sm text-content-tertiary">{ui(t, 'design.ui.permit.no_items')}</p>
              ) : (
                <ul className="divide-y divide-border-light rounded-md border border-border-light" data-testid="permit-items">
                  {permit.items.map((item) => {
                    const state = itemState(item);
                    return (
                      <li key={item.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm" data-testid="permit-item" data-state={state}>
                        {state === 'ready' ? (
                          <CheckCircle2 size={14} className="text-semantic-success" aria-hidden />
                        ) : (
                          <CircleAlert size={14} className="text-semantic-warning" aria-hidden />
                        )}
                        <span className="text-xs text-content-tertiary">{vocab(t, PERMIT_ITEM, item.kind)}</span>
                        <span className="text-content-primary">{item.title}</span>
                        {!item.required && <span className="text-xs text-content-tertiary">{ui(t, 'design.ui.permit.optional')}</span>}
                        <span className="ml-auto text-xs text-content-secondary">
                          {state === 'ready'
                            ? ui(t, 'design.ui.permit.item_ready')
                            : state === 'not_shared'
                              ? ui(t, 'design.ui.permit.item_not_shared')
                              : ui(t, 'design.ui.permit.item_missing')}
                        </span>
                        {assembling && (
                          <WriteButton
                            size="sm"
                            variant="ghost"
                            disabled={action.pending}
                            onClick={async () => {
                              if (
                                await confirmState.confirm({
                                  title: ui(t, 'design.ui.permit.item_remove_title'),
                                  message: ui(t, 'design.ui.permit.item_remove_body'),
                                  confirmLabel: ui(t, 'design.ui.permit.item_remove'),
                                })
                              ) {
                                action.run(() => removePermitItem(ctx.projectId, permit.id, item.id));
                              }
                            }}
                          >
                            {ui(t, 'design.ui.permit.item_remove')}
                          </WriteButton>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
              {assembling && (
                <WriteButton size="sm" variant="secondary" onClick={() => setDialog({ kind: 'item', permit })} data-testid="permit-item-add">
                  {ui(t, 'design.ui.permit.item_add')}
                </WriteButton>
              )}

              {(approved || permit.conditions.length > 0) && (
                <div className="space-y-2" data-testid="permit-conditions">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-sm font-medium text-content-primary">{ui(t, 'design.ui.permit.conditions_title')}</h4>
                    {approved && (
                      <WriteButton size="sm" variant="secondary" onClick={() => setDialog({ kind: 'condition', permit })} data-testid="condition-add">
                        {ui(t, 'design.ui.permit.condition_add')}
                      </WriteButton>
                    )}
                  </div>
                  {permit.conditions.length === 0 && <p className="text-sm text-content-tertiary">{ui(t, 'design.ui.permit.conditions_empty')}</p>}
                  {permit.conditions.map((condition) => (
                    <div key={condition.id} className="rounded-md bg-surface-secondary p-2 text-sm" data-testid="permit-condition">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-content-secondary">{vocab(t, CONDITION_STATE, condition.state)}</span>
                        {condition.owner_user_id && (
                          <span className="text-xs text-content-secondary">
                            {ctx.personName(condition.owner_user_id) ?? ui(t, 'design.ui.team.project_member')}
                          </span>
                        )}
                        {condition.due_date && (
                          <span className="text-xs text-content-secondary">{ui(t, 'design.ui.permit.due', { date: fmtDate(condition.due_date) })}</span>
                        )}
                        {condition.state === 'proposed' && (
                          <span className="ml-auto flex gap-1">
                            <WriteButton need="manage"
                              size="sm"
                              variant="secondary"
                              disabled={action.pending}
                              onClick={() => action.run(() => decidePermitCondition(ctx.projectId, permit.id, condition.id, true))}
                              data-testid="condition-confirm"
                            >
                              {ui(t, 'design.ui.permit.condition_confirm')}
                            </WriteButton>
                            <WriteButton need="manage"
                              size="sm"
                              variant="ghost"
                              disabled={action.pending}
                              onClick={() => action.run(() => decidePermitCondition(ctx.projectId, permit.id, condition.id, false))}
                            >
                              {ui(t, 'design.ui.permit.condition_dismiss')}
                            </WriteButton>
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-content-primary">{condition.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </section>
          );
        })}

      {dialog?.kind === 'permit' && (
        <FormDialog
          projectId={ctx.projectId}
          title={dialog.permit ? ui(t, 'design.ui.permit.edit') : ui(t, 'design.ui.permit.add')}
          fields={permitFields(!!dialog.permit)}
          initial={permitValues(dialog.permit)}
          submitLabel={dialog.permit ? ui(t, 'design.ui.action.save') : ui(t, 'design.ui.permit.add')}
          submit={(values) =>
            dialog.permit
              ? updatePermit(ctx.projectId, dialog.permit.id, changedFields<PermitInput>(permitValues(dialog.permit), values, ['target_submission_date', 'authority_submission_id', 'review_cycle_id']))
              : createPermit(ctx.projectId, filledFields<PermitInput>(values))
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="permit-form"
        />
      )}
      {dialog?.kind === 'item' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.permit.item_add')}
          fields={itemFields}
          initial={{ kind: '', container_id: '', report_id: '', title: '', required: true }}
          submitLabel={ui(t, 'design.ui.permit.item_add')}
          submit={(values) => addPermitItem(ctx.projectId, dialog.permit.id, itemBody(values))}
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="permit-item-form"
        />
      )}
      {dialog?.kind === 'condition' && (
        <FormDialog
          projectId={ctx.projectId}
          title={ui(t, 'design.ui.permit.condition_add')}
          subtitle={ui(t, 'design.ui.permit.condition_body')}
          fields={[
            { name: 'text', label: ui(t, 'design.ui.permit.condition_text'), type: 'textarea', required: true },
            { name: 'owner_user_id', label: ui(t, 'design.ui.permit.condition_owner'), type: 'person' },
            { name: 'due_date', label: ui(t, 'design.ui.permit.condition_due'), type: 'date' },
          ]}
          initial={{ text: '', owner_user_id: '', due_date: '' }}
          submitLabel={ui(t, 'design.ui.permit.condition_add')}
          submit={(values) =>
            proposePermitConditions(ctx.projectId, dialog.permit.id, [
              { text: str(values, 'text'), owner_user_id: str(values, 'owner_user_id') || null, due_date: str(values, 'due_date') || null },
            ])
          }
          onClose={() => setDialog(null)}
          onDone={ctx.onChanged}
          testId="condition-form"
        />
      )}
    </div>
  );
}
