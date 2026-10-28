// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Acceptance units: the parts of the works that are formally accepted, the
// regime each follows and what acceptance sets in motion. The acceptance
// itself is not recorded here. It follows from the handover act issued in
// construction control, so this screen plans, requests and refuses, and after
// acceptance lets a person confirm each legal effect one by one.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Handshake, Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  confirmEffect,
  createUnit,
  deleteUnit,
  patchUnit,
  recordUnitDates,
  refuseUnit,
  requestAcceptance,
  unitAction,
  type AcceptanceUnit,
  type RegimeEffect,
} from './api';
import { ExportButtons } from './ExportButtons';
import { useAcceptanceUnits, useQcWrite } from './hooks';
import { ClosedReasons, SharedReasons } from './ClosedReasons';
import { OptionPicker } from './OptionPicker';
import {
  ACCEPTANCE_ACTION,
  ACCEPTANCE_KIND,
  ACCEPTANCE_STATE,
  DEEMED_TRIGGER,
  LEGAL_EFFECT,
  UNMET_KIND,
  catalogueName,
  nameIn,
  gate,
  vocab,
  type LabelContext,
  type TFn,
} from './labels';
import { packageName, type PanelProps } from './panel';
import {
  ACCEPTANCE_TONE,
  Field,
  FormDialog,
  Hint,
  RefusalNote,
  ReviewBadge,
  Section,
  StateBadge,
  VocabSelect,
  inputCls,
} from './QualityBits';
import {
  ACCEPTANCE_ACTIONS,
  RECORDING_UNIT_ACTIONS,
  effectInForce,
  isAccepted,
  lines,
  may,
  refChange,
  sharedReasons,
  type AcceptanceAction,
} from './rules';

const KINDS = ['partial_package', 'partial_section', 'total', 'handover_to_operation', 'authority'] as const;

type Dialog =
  | { kind: 'unit'; unit: AcceptanceUnit | null }
  | { kind: 'request'; unit: AcceptanceUnit }
  | { kind: 'refuse'; unit: AcceptanceUnit }
  | { kind: 'dates'; unit: AcceptanceUnit }
  | { kind: 'effect'; unit: AcceptanceUnit; effect: RegimeEffect }
  | null;

/** What a legal effect means under the unit's regime: the regime's own wording when the locale has it. */
function effectName(labels: LabelContext, effect: RegimeEffect): string {
  if (effect.detail_key && labels.exists(effect.detail_key)) return labels.t(effect.detail_key);
  return vocab(labels.t, LEGAL_EFFECT, effect.effect);
}

const unitActions = (u: AcceptanceUnit): string[] => ['edit', 'delete', 'confirm_effect', ...(ACCEPTANCE_ACTIONS[u.state] ?? [])];

export function AcceptancePanel(props: PanelProps) {
  const { projectId, concept, labels, manage } = props;
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const units = useAcceptanceUnits(projectId);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [removing, setRemoving] = useState<AcceptanceUnit | null>(null);

  if (units.isLoading) return <SkeletonTable rows={4} columns={5} />;
  if (units.isError) {
    return (
      <ErrorState
        title={t('qualityConcept.acceptance.load_failed', { defaultValue: 'The acceptance units could not be loaded' })}
        hint={getErrorMessage(units.error)}
        onRetry={() => units.refetch()}
      />
    );
  }
  const rows = units.data ?? [];

  const run = (unit: AcceptanceUnit, action: AcceptanceAction) => {
    if (action === 'request') setDialog({ kind: 'request', unit });
    else if (action === 'refuse') setDialog({ kind: 'refuse', unit });
    else if (action === 'record_dates') setDialog({ kind: 'dates', unit });
    else if (action !== 'confirm_effects') write.send(() => unitAction(projectId, unit.id, action));
  };

  const dialogs = (
    <>
      {dialog?.kind === 'unit' && <UnitDialog {...props} unit={dialog.unit} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'request' && <RequestDialog {...props} unit={dialog.unit} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'refuse' && <RefuseDialog {...props} unit={dialog.unit} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'dates' && <DatesDialog {...props} unit={dialog.unit} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'effect' && (
        <EffectDialog {...props} unit={dialog.unit} effect={dialog.effect} onClose={() => setDialog(null)} />
      )}
      <ConfirmDialog
        open={!!removing}
        variant="danger"
        loading={write.pending}
        title={t('qualityConcept.acceptance.remove_title', { defaultValue: 'Remove this acceptance unit?' })}
        message={t('qualityConcept.acceptance.remove_body', {
          defaultValue: '{{name}} is taken out of the acceptance plan.',
          name: [removing?.code, removing?.title].filter(Boolean).join(' '),
        })}
        confirmLabel={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
        cancelLabel={t('qualityConcept.common.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const row = removing;
          setRemoving(null);
          if (row) write.send(() => deleteUnit(projectId, row.id));
        }}
      />
    </>
  );

  if (rows.length === 0) {
    return (
      <div className="space-y-4" data-testid="acceptance-panel">
        <EmptyState
          icon={<Handshake size={28} />}
          title={t('qualityConcept.acceptance.empty_title', { defaultValue: 'No acceptance planned yet' })}
          description={t('qualityConcept.acceptance.empty_body', {
            defaultValue:
              'An acceptance unit is a part of the works that is formally accepted: a package, a section, the whole works or the handover to operation. Plan at least the whole works and the handover to operation.',
          })}
          action={
            manage
              ? {
                  label: t('qualityConcept.acceptance.add', { defaultValue: 'Add acceptance unit' }),
                  onClick: () => setDialog({ kind: 'unit', unit: null }),
                }
              : undefined
          }
        />
        {dialogs}
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="acceptance-panel">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <ExportButtons projectId={projectId} what="acceptance" />
        <Button icon={<Plus size={14} />} disabled={!manage} onClick={() => setDialog({ kind: 'unit', unit: null })} data-testid="unit-add">
          {t('qualityConcept.acceptance.add', { defaultValue: 'Add acceptance unit' })}
        </Button>
      </div>
      <RefusalNote refusal={write.refusal} violations={write.violations} />

      <SharedReasons codes={sharedReasons(rows, unitActions)} />
      {rows.map((u) => {
        const inForce = u.effects_applied.filter(effectInForce);
        const applied = new Set(inForce.map((e) => e.effect));
        const open = u.state === 'requested' || u.state === 'inspection_scheduled';
        return (
          <Section
            key={u.id}
            testId="acceptance-unit"
            title={[u.code, u.title].filter(Boolean).join(' ') || vocab(t as TFn, ACCEPTANCE_KIND, u.kind)}
            description={
              u.planned_date
                ? t('qualityConcept.acceptance.kind_planned', {
                    defaultValue: '{{kind}}, planned for {{date}}',
                    kind: vocab(t as TFn, ACCEPTANCE_KIND, u.kind),
                    date: fmtDate(u.planned_date),
                  })
                : vocab(t as TFn, ACCEPTANCE_KIND, u.kind)
            }
            action={
              <div className="flex flex-wrap items-center gap-1">
                <StateBadge map={ACCEPTANCE_STATE} tones={ACCEPTANCE_TONE} code={u.state} testId="unit-state" />
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Pencil size={14} />}
                  aria-label={t('qualityConcept.common.edit', { defaultValue: 'Edit' })}
                  {...gate(t as TFn, u, 'edit', manage)}
                  onClick={() => setDialog({ kind: 'unit', unit: u })}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={14} />}
                  aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
                  {...gate(t as TFn, u, 'delete', manage)}
                  onClick={() => setRemoving(u)}
                />
              </div>
            }
          >
            <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="unit-regime">
              {u.regime ? (
                <>
                  <span className="text-content-primary">{catalogueName(labels, u.regime)}</span>
                  <span className="text-xs text-content-tertiary">{u.regime.act_name}</span>
                  <ReviewBadge status={u.regime.review_status} />
                </>
              ) : (
                <span className="text-semantic-error">
                  {t('qualityConcept.acceptance.no_regime', { defaultValue: 'No acceptance regime chosen yet' })}
                </span>
              )}
              {u.package_refs.length > 0 && (
                <span className="text-xs text-content-secondary">{fmtList(u.package_refs.map((r) => packageName(concept, r)))}</span>
              )}
            </div>

            {u.unmet.length > 0 && (
              <div className="mt-3" data-testid="unit-unmet">
                <p className="mb-1 text-xs font-semibold text-content-secondary">
                  {t('qualityConcept.acceptance.unmet_title', { defaultValue: 'Still open before acceptance' })}
                </p>
                <ul className="space-y-0.5 text-sm text-content-primary">
                  {u.unmet.map((x, i) => (
                    <li key={`${x.kind}:${x.ref}:${i}`}>
                      {vocab(t as TFn, UNMET_KIND, x.kind)}
                      {(x.label || x.kind === 'documentation') && (
                        <span className="text-content-tertiary"> {x.label || x.ref}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {u.deemed.length > 0 && (
              <div className="mt-3" data-testid="unit-deemed">
                <p className="mb-1 text-xs font-semibold text-content-secondary">
                  {t('qualityConcept.acceptance.deemed_title', { defaultValue: 'Acceptance without a signature' })}
                </p>
                <ul className="space-y-1 text-sm">
                  {u.deemed.map((d) => (
                    <li key={d.trigger} className="flex flex-wrap items-center gap-2">
                      <span className="text-content-primary">
                        {d.deemed_on
                          ? t('qualityConcept.acceptance.deemed_line', {
                              defaultValue: '{{trigger}} on {{from}}: the works count as accepted on {{date}}',
                              trigger: vocab(t as TFn, DEEMED_TRIGGER, d.trigger),
                              from: fmtDate(d.from),
                              date: fmtDate(d.deemed_on),
                            })
                          : t('qualityConcept.acceptance.deemed_needs_deadline', {
                              defaultValue: '{{trigger}} on {{from}}: counts only once a deadline is set',
                              trigger: vocab(t as TFn, DEEMED_TRIGGER, d.trigger),
                              from: fmtDate(d.from),
                            })}
                      </span>
                      {d.days_left !== null && (
                        <span className={d.days_left <= 0 ? 'text-xs font-medium text-semantic-error' : 'text-xs text-content-secondary'}>
                          {d.days_left <= 0
                            ? t('qualityConcept.acceptance.deemed_passed', { defaultValue: 'This date has passed' })
                            : t('qualityConcept.acceptance.deemed_days', { defaultValue: 'Days left: {{days}}', days: d.days_left })}
                        </span>
                      )}
                      <ReviewBadge status={d.review_status} />
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {u.state === 'refused' && (
              <div className="mt-3 text-sm" data-testid="unit-refusal">
                <p className="text-content-primary">
                  {t('qualityConcept.acceptance.refused_because', { defaultValue: 'Refused because: {{reason}}', reason: u.refusal_reason })}
                </p>
                {u.refusal_defects.length > 0 && <p className="text-content-secondary">{fmtList(u.refusal_defects)}</p>}
              </div>
            )}

            {open && (
              <p className="mt-3 text-sm text-content-secondary" data-testid="unit-accept-elsewhere">
                {t('qualityConcept.acceptance.accept_elsewhere', {
                  defaultValue: 'The acceptance is recorded by issuing the handover act in construction control.',
                })}{' '}
                <Link className="text-oe-blue-text underline" to={`/projects/${projectId}/construction-control`}>
                  {t('qualityConcept.stages.open_construction_control', { defaultValue: 'Open construction control' })}
                </Link>
              </p>
            )}
            {u.handover_package?.label && (
              <p className="mt-1 text-sm text-content-secondary" data-testid="unit-handover-act">
                {t('qualityConcept.acceptance.handover_act', {
                  defaultValue: 'Handover act: {{label}}',
                  label: u.handover_package.label,
                })}
              </p>
            )}

            {isAccepted(u.state) && (
              <div className="mt-3" data-testid="unit-effects">
                <p className="mb-1 text-xs font-semibold text-content-secondary">
                  {t('qualityConcept.acceptance.effects_title', { defaultValue: 'What the acceptance sets in motion' })}
                </p>
                {u.accepted_on && (
                  <p className="mb-1 text-sm text-content-secondary">
                    {t('qualityConcept.acceptance.accepted_on', { defaultValue: 'Accepted on {{date}}', date: fmtDate(u.accepted_on) })}
                  </p>
                )}
                {u.effects_proposed.length === 0 && inForce.length === 0 ? (
                  <Hint>
                    {t('qualityConcept.acceptance.effects_none', { defaultValue: 'The regime names no effects for this unit.' })}
                  </Hint>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {inForce.map((e) => (
                      <li key={e.id} className="flex flex-wrap items-center gap-2" data-testid="effect-applied">
                        <span className="text-content-primary">{vocab(t as TFn, LEGAL_EFFECT, e.effect)}</span>
                        <span className="text-xs text-semantic-success">
                          {e.effective_date
                            ? t('qualityConcept.acceptance.effect_confirmed_on', {
                                defaultValue: 'Confirmed, in effect from {{date}}',
                                date: fmtDate(e.effective_date),
                              })
                            : t('qualityConcept.acceptance.effect_confirmed', { defaultValue: 'Confirmed' })}
                        </span>
                      </li>
                    ))}
                    {u.effects_proposed
                      .filter((e) => !applied.has(e.effect))
                      .map((e) => (
                        <li key={e.effect} className="flex flex-wrap items-center gap-2" data-testid="effect-proposed">
                          <span className="text-content-primary">{effectName(labels, e)}</span>
                          {e.value && <span className="text-xs text-content-secondary">{e.value}</span>}
                          <ReviewBadge status={e.review_status} />
                          <Button size="sm" variant="secondary" className="ml-auto" {...gate(t as TFn, u, 'confirm_effect', manage)} onClick={() => setDialog({ kind: 'effect', unit: u, effect: e })} data-testid="effect-confirm">
                            {t('qualityConcept.actions.confirmEffect', { defaultValue: 'Confirm effect' })}
                          </Button>
                        </li>
                      ))}
                  </ul>
                )}
              </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              {(ACCEPTANCE_ACTIONS[u.state] ?? [])
                .filter((a) => a !== 'confirm_effects')
                .map((action) => (
                  <Button
                    key={action}
                    size="sm"
                    variant={action === 'request' ? 'primary' : action === 'refuse' || action === 'withdraw' ? 'ghost' : 'secondary'}
                    loading={write.pending}
                    {...gate(t as TFn, u, action, manage || RECORDING_UNIT_ACTIONS.has(action))}
                    onClick={() => run(u, action)}
                    data-testid={`unit-action-${action}`}
                  >
                    {vocab(t as TFn, ACCEPTANCE_ACTION, action)}
                  </Button>
                ))}
              <ClosedReasons row={u} actions={unitActions(u)} skip={sharedReasons(rows, unitActions)} />
            </div>
          </Section>
        );
      })}
      {dialogs}
    </div>
  );
}

function UnitDialog({
  projectId,
  concept,
  catalogue,
  labels,
  unit,
  onClose,
}: PanelProps & { unit: AcceptanceUnit | null; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const regimes = catalogue?.acceptance_regimes ?? [];
  const [code, setCode] = useState(unit?.code ?? '');
  const [title, setTitle] = useState(unit?.title ?? '');
  const [kind, setKind] = useState(unit?.kind ?? 'total');
  const [regime, setRegime] = useState(unit?.regime_code ?? '');
  const [refs, setRefs] = useState<string[]>(unit?.package_refs ?? []);
  const [section, setSection] = useState(unit?.section_ref ?? '');
  const [planned, setPlanned] = useState(unit?.planned_date ?? '');
  const [activity, setActivity] = useState(unit?.schedule_activity_id ?? '');
  const [act, setAct] = useState(unit?.handover_package_id ?? '');
  const problem =
    !code.trim() && !title.trim()
      ? t('qualityConcept.acceptance.problem_name', { defaultValue: 'Give the unit a code or a title' })
      : kind === 'partial_package' && refs.length === 0
        ? t('qualityConcept.acceptance.problem_package', { defaultValue: 'A partial acceptance by package names at least one package' })
        : null;
  const body = {
    code: code.trim(),
    title: title.trim(),
    package_refs: refs,
    section_ref: section.trim(),
    regime_code: regime || null,
    planned_date: planned || null,
    ...refChange('schedule_activity_id', unit?.schedule_activity_id, activity),
  };

  return (
    <FormDialog
      open
      testId="unit-dialog"
      title={
        unit
          ? t('qualityConcept.acceptance.edit_title', { defaultValue: 'Edit acceptance unit' })
          : t('qualityConcept.acceptance.add', { defaultValue: 'Add acceptance unit' })
      }
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      violations={write.violations}
      problem={problem}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(
          () =>
            unit
              ? patchUnit(projectId, unit.id, { ...body, ...refChange('handover_package_id', unit.handover_package_id, act) })
              : createUnit(projectId, { ...body, kind }),
          onClose,
        )
      }
    >
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t('qualityConcept.stages.code', { defaultValue: 'Code' })}>
          <input className={inputCls} value={code} onChange={(e) => setCode(e.target.value)} data-testid="unit-code" />
        </Field>
        <div className="md:col-span-2">
          <Field label={t('qualityConcept.standards.name', { defaultValue: 'Title' })}>
            <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} data-testid="unit-title" />
          </Field>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Field required label={t('qualityConcept.acceptance.kind', { defaultValue: 'What is accepted' })}>
          {unit ? (
            <p className="py-1.5 text-sm text-content-primary">{vocab(t as TFn, ACCEPTANCE_KIND, unit.kind)}</p>
          ) : (
            <VocabSelect map={ACCEPTANCE_KIND} codes={KINDS} value={kind} onChange={setKind} testId="unit-kind" />
          )}
        </Field>
        <Field
          label={t('qualityConcept.acceptance.regime', { defaultValue: 'Acceptance regime' })}
          hint={t('qualityConcept.acceptance.regime_hint', {
            defaultValue: 'The contract rules the acceptance follows. They decide the deadlines and the effects.',
          })}
        >
          <select className={inputCls} value={regime} onChange={(e) => setRegime(e.target.value)} data-testid="unit-regime-select">
            <option value="">{t('qualityConcept.common.choose', { defaultValue: 'Choose' })}</option>
            {regimes.map((r) => (
              <option key={r.code} value={r.code}>
                {nameIn(labels, regimes, r.code)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('qualityConcept.acceptance.planned_date', { defaultValue: 'Planned date' })}>
          <input type="date" className={inputCls} value={planned} onChange={(e) => setPlanned(e.target.value)} />
        </Field>
        <Field label={t('qualityConcept.acceptance.section', { defaultValue: 'Section of the works' })}>
          <input className={inputCls} value={section} onChange={(e) => setSection(e.target.value)} />
        </Field>
      </div>
      {concept.applicable_packages.length > 0 && (
        <Field label={t('qualityConcept.acceptance.packages', { defaultValue: 'Packages it covers' })}>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {concept.applicable_packages.map((p) => (
              <span key={p.ref} className="inline-flex items-center gap-1.5 text-sm text-content-primary">
                <input
                  type="checkbox"
                  aria-label={packageName(concept, p.ref)}
                  checked={refs.includes(p.ref)}
                  onChange={(e) => setRefs(e.target.checked ? [...refs, p.ref] : refs.filter((r) => r !== p.ref))}
                />
                {packageName(concept, p.ref)}
              </span>
            ))}
          </div>
        </Field>
      )}
      <Field label={t('qualityConcept.acceptance.activity', { defaultValue: 'Schedule activity' })}>
        <OptionPicker projectId={projectId} kind="schedule_activity" value={activity} onChange={setActivity} testId="unit-activity" />
      </Field>
      {unit && may(unit, 'link_handover', true) && (
        <Field label={t('qualityConcept.acceptance.handover_pick', { defaultValue: 'Handover act' })}>
          <OptionPicker projectId={projectId} kind="handover_package" value={act} onChange={setAct} testId="unit-handover" />
        </Field>
      )}
    </FormDialog>
  );
}

function RequestDialog({ projectId, unit, onClose }: PanelProps & { unit: AcceptanceUnit; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [withReservations, setWithReservations] = useState(false);
  const reservable = new Set(unit.regime?.reservable ?? []);
  const canReserve = unit.unmet.length > 0 && unit.unmet.every((x) => reservable.has(x.kind));

  return (
    <FormDialog
      open
      testId="unit-request-dialog"
      title={vocab(t as TFn, ACCEPTANCE_ACTION, 'request')}
      subtitle={[unit.code, unit.title].filter(Boolean).join(' ')}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      violations={write.violations}
      submitLabel={vocab(t as TFn, ACCEPTANCE_ACTION, 'request')}
      onSubmit={() => write.send(() => requestAcceptance(projectId, unit.id, withReservations), onClose)}
    >
      {unit.unmet.length === 0 ? (
        <Hint>
          {t('qualityConcept.acceptance.request_ready', {
            defaultValue: 'Every precondition is met. The request goes to the client for inspection.',
          })}
        </Hint>
      ) : (
        <>
          <p className="text-sm text-content-primary">
            {t('qualityConcept.acceptance.request_open', {
              defaultValue: 'Some points are still open. An acceptance can only be requested with them carried as reservations.',
            })}
          </p>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-content-primary">
            {unit.unmet.map((x, i) => (
              <li key={`${x.kind}:${x.ref}:${i}`}>{vocab(t as TFn, UNMET_KIND, x.kind)}</li>
            ))}
          </ul>
          <label className="flex items-start gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={withReservations}
              onChange={(e) => setWithReservations(e.target.checked)}
              data-testid="request-with-reservations"
            />
            {t('qualityConcept.acceptance.with_reservations', { defaultValue: 'Request with these points as reservations' })}
          </label>
          {!canReserve && (
            <Hint>
              {t('qualityConcept.acceptance.not_reservable', {
                defaultValue: 'Under this regime not every open point can be a reservation. The request may be refused.',
              })}
            </Hint>
          )}
        </>
      )}
    </FormDialog>
  );
}

function RefuseDialog({ projectId, unit, onClose }: PanelProps & { unit: AcceptanceUnit; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [reason, setReason] = useState('');
  const [defects, setDefects] = useState('');
  const needsDefect = !!unit.regime?.refusal_needs_defect;
  const problem = !reason.trim()
    ? t('qualityConcept.common.problem_reason', { defaultValue: 'Write down the reason' })
    : needsDefect && lines(defects).length === 0
      ? t('qualityConcept.acceptance.problem_defect', { defaultValue: 'Under this regime a refusal names at least one defect' })
      : null;

  return (
    <FormDialog
      open
      testId="unit-refuse-dialog"
      title={vocab(t as TFn, ACCEPTANCE_ACTION, 'refuse')}
      subtitle={[unit.code, unit.title].filter(Boolean).join(' ')}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={problem}
      submitLabel={vocab(t as TFn, ACCEPTANCE_ACTION, 'refuse')}
      onSubmit={() => write.send(() => refuseUnit(projectId, unit.id, { rationale: reason.trim(), defects: lines(defects) }), onClose)}
    >
      <Field required label={t('qualityConcept.common.reason', { defaultValue: 'Reason' })}>
        <textarea rows={2} className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="refuse-reason" />
      </Field>
      <Field
        required={needsDefect}
        label={t('qualityConcept.acceptance.defects', { defaultValue: 'Defects, one per line' })}
      >
        <textarea rows={3} className={inputCls} value={defects} onChange={(e) => setDefects(e.target.value)} data-testid="refuse-defects" />
      </Field>
    </FormDialog>
  );
}

function DatesDialog({ projectId, unit, onClose }: PanelProps & { unit: AcceptanceUnit; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [notice, setNotice] = useState(unit.completion_notice_at ?? '');
  const [use, setUse] = useState(unit.use_started_at ?? '');
  const [deadline, setDeadline] = useState(unit.deadline_at ?? '');

  return (
    <FormDialog
      open
      testId="unit-dates-dialog"
      title={vocab(t as TFn, ACCEPTANCE_ACTION, 'record_dates')}
      subtitle={t('qualityConcept.acceptance.dates_body', {
        defaultValue:
          'These dates can start a period after which the works count as accepted even without a signature. Record them as they happen.',
      })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(
          () =>
            recordUnitDates(projectId, unit.id, {
              completion_notice_at: notice || null,
              use_started_at: use || null,
              deadline_at: deadline || null,
            }),
          onClose,
        )
      }
    >
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={vocab(t as TFn, DEEMED_TRIGGER, 'completion_notice')}>
          <input type="date" className={inputCls} value={notice} onChange={(e) => setNotice(e.target.value)} data-testid="date-notice" />
        </Field>
        <Field label={vocab(t as TFn, DEEMED_TRIGGER, 'use_start')}>
          <input type="date" className={inputCls} value={use} onChange={(e) => setUse(e.target.value)} />
        </Field>
        <Field label={vocab(t as TFn, DEEMED_TRIGGER, 'deadline_set')}>
          <input type="date" className={inputCls} value={deadline} onChange={(e) => setDeadline(e.target.value)} />
        </Field>
      </div>
    </FormDialog>
  );
}

function EffectDialog({
  projectId,
  labels,
  unit,
  effect,
  onClose,
}: PanelProps & { unit: AcceptanceUnit; effect: RegimeEffect; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [date, setDate] = useState(unit.accepted_on ?? '');

  return (
    <FormDialog
      open
      size="sm"
      testId="effect-dialog"
      title={t('qualityConcept.actions.confirmEffect', { defaultValue: 'Confirm effect' })}
      subtitle={effectName(labels, effect)}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      submitLabel={t('qualityConcept.actions.confirmEffect', { defaultValue: 'Confirm effect' })}
      onSubmit={() =>
        write.send(() => confirmEffect(projectId, unit.id, { effect: effect.effect, effective_date: date || null }), onClose)
      }
    >
      <Hint>
        {t('qualityConcept.acceptance.effect_hint', {
          defaultValue:
            'Nothing is applied on its own. You confirm that this effect holds for this unit, and from which day. Check it against the contract first.',
        })}
      </Hint>
      {effect.review_status === 'unconfirmed' && <ReviewBadge status={effect.review_status} />}
      <Field
        label={t('qualityConcept.acceptance.effective_date', { defaultValue: 'In effect from' })}
        hint={t('qualityConcept.acceptance.effective_date_hint', { defaultValue: 'Leave empty to use the acceptance date.' })}
      >
        <input type="date" className={inputCls} value={date} onChange={(e) => setDate(e.target.value)} data-testid="effect-date" />
      </Field>
    </FormDialog>
  );
}
