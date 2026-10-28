// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Certification targets: the scheme and level the owner wants, the credits
// that are meant to reach it and how far they have come. The point totals are
// the server's; nothing is summed here.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Award, Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';

import {
  addCredits,
  createCertification,
  deleteCertification,
  deleteCredit,
  patchCertification,
  patchCredit,
  transitionCertification,
  type Certification,
  type CertificationAction,
  type Credit,
  type CreditAction,
} from './api';
import { EvidenceLinks } from './EvidenceLinks';
import { ExportButtons } from './ExportButtons';
import { useCertifications, useQcWrite } from './hooks';
import { ClosedReasons, SharedReasons } from './ClosedReasons';
import { OptionPicker } from './OptionPicker';
import {
  CERTIFICATION_ACTION,
  CERTIFICATION_SCOPE,
  CERTIFICATION_STATE,
  CREDIT_ACTION,
  CREDIT_STATE,
  catalogueName,
  nameIn,
  gate,
  humanizeCode,
  vocab,
  type TFn,
} from './labels';
import type { PanelProps } from './panel';
import {
  CERTIFICATION_TONE,
  CREDIT_TONE,
  Field,
  FindingList,
  FormDialog,
  Hint,
  RefusalNote,
  ReviewBadge,
  Section,
  StateBadge,
  VocabSelect,
  inputCls,
} from './QualityBits';
import { CERTIFICATION_ACTIONS, CREDIT_ACTIONS, needsAchievedLevel, needsRationale, pointsString, refChange, sharedReasons } from './rules';

const SCOPES = ['building', 'plant', 'operation'] as const;

type Dialog =
  | { kind: 'target'; target: Certification | null }
  | { kind: 'transition'; target: Certification; action: CertificationAction }
  | { kind: 'credit'; target: Certification }
  | { kind: 'achieve'; credit: Credit }
  | null;

const targetActions = (target: Certification): string[] => [
  'edit',
  'delete',
  'add_credits',
  ...(CERTIFICATION_ACTIONS[target.state] ?? []),
];
const creditActions = (c: Credit): string[] => ['delete', ...(CREDIT_ACTIONS[c.state] ?? [])];

export function CertificationPanel(props: PanelProps) {
  const { projectId, catalogue, labels, personName, manage } = props;
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const query = useCertifications(projectId);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [removing, setRemoving] = useState<{ target?: Certification; credit?: Credit } | null>(null);
  const [linksOf, setLinksOf] = useState<string | null>(null);

  if (query.isLoading) return <SkeletonTable rows={4} columns={5} />;
  if (query.isError) {
    return (
      <ErrorState
        title={t('qualityConcept.certification.load_failed', { defaultValue: 'The certification targets could not be loaded' })}
        hint={getErrorMessage(query.error)}
        onRetry={() => query.refetch()}
      />
    );
  }
  const targets = query.data?.items ?? [];
  const schemes = catalogue?.certification_schemes ?? [];
  const levelName = (target: Certification, code: string | null) =>
    nameIn(labels, schemes.find((s) => s.code === target.scheme_code)?.levels, code);

  const runCredit = (credit: Credit, action: CreditAction) => {
    if (action === 'achieve') setDialog({ kind: 'achieve', credit });
    else write.send(() => patchCredit(projectId, credit.id, { action }));
  };

  return (
    <div className="space-y-4" data-testid="certification-panel">
      <RefusalNote refusal={write.refusal} violations={write.violations} />
      {targets.length === 0 ? (
        <EmptyState
          icon={<Award size={28} />}
          title={t('qualityConcept.certification.empty_title', { defaultValue: 'No certification target' })}
          description={t('qualityConcept.certification.empty_body', {
            defaultValue:
              'Certification is optional. If the owner wants a sustainability or quality label, name the scheme and the level here, then track the credits that are meant to reach it.',
          })}
          action={
            manage
              ? {
                  label: t('qualityConcept.certification.add', { defaultValue: 'Add certification target' }),
                  onClick: () => setDialog({ kind: 'target', target: null }),
                }
              : undefined
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <ExportButtons projectId={projectId} what="certification" />
            <Button icon={<Plus size={14} />} disabled={!manage} onClick={() => setDialog({ kind: 'target', target: null })} data-testid="certification-add">
              {t('qualityConcept.certification.add', { defaultValue: 'Add certification target' })}
            </Button>
          </div>
          <FindingList findings={query.data?.findings ?? []} />
          <SharedReasons codes={sharedReasons(targets, targetActions)} />
          {targets.map((target) => {
            const scheme = schemes.find((s) => s.code === target.scheme_code);
            return (
              <Section
                key={target.id}
                testId="certification-target"
                title={catalogueName(labels, scheme, target.scheme_code)}
                description={t('qualityConcept.certification.target_line', {
                  defaultValue: 'Target level: {{level}}. Applies to: {{scope}}.',
                  level: levelName(target, target.target_level),
                  scope: vocab(t as TFn, CERTIFICATION_SCOPE, target.scope),
                })}
                action={
                  <div className="flex flex-wrap items-center gap-1">
                    <StateBadge map={CERTIFICATION_STATE} tones={CERTIFICATION_TONE} code={target.state} testId="certification-state" />
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Pencil size={14} />}
                      aria-label={t('qualityConcept.common.edit', { defaultValue: 'Edit' })}
                      {...gate(t as TFn, target, 'edit', manage)}
                      onClick={() => setDialog({ kind: 'target', target })}
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Trash2 size={14} />}
                      aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
                      {...gate(t as TFn, target, 'delete', manage)}
                      onClick={() => setRemoving({ target })}
                    />
                  </div>
                }
              >
                <dl className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                  <div>
                    <dt className="text-xs text-content-tertiary">
                      {t('qualityConcept.certification.points', { defaultValue: 'Points achieved of targeted' })}
                    </dt>
                    <dd className="font-medium text-content-primary" data-testid="certification-points">
                      {t('qualityConcept.common.of', {
                        defaultValue: '{{done}} of {{total}}',
                        done: fmtNumber(target.points_achieved, 1),
                        total: fmtNumber(target.points_targeted, 1),
                      })}
                    </dd>
                  </div>
                  {target.points_available && (
                    <div>
                      <dt className="text-xs text-content-tertiary">
                        {t('qualityConcept.certification.points_available_label', { defaultValue: 'Points available' })}
                      </dt>
                      <dd className="font-medium text-content-primary">{fmtNumber(target.points_available, 1)}</dd>
                    </div>
                  )}
                  {target.achieved_level && (
                    <div>
                      <dt className="text-xs text-content-tertiary">
                        {t('qualityConcept.certification.achieved_level', { defaultValue: 'Level achieved' })}
                      </dt>
                      <dd className="font-medium text-content-primary">{levelName(target, target.achieved_level)}</dd>
                    </div>
                  )}
                  {target.registration_no && (
                    <div>
                      <dt className="text-xs text-content-tertiary">
                        {t('qualityConcept.certification.registration_no', { defaultValue: 'Registration number' })}
                      </dt>
                      <dd className="text-content-primary">{target.registration_no}</dd>
                    </div>
                  )}
                  {target.certified_on && (
                    <div>
                      <dt className="text-xs text-content-tertiary">
                        {t('qualityConcept.certification.certified_on', { defaultValue: 'Certified on' })}
                      </dt>
                      <dd className="text-content-primary">{fmtDate(target.certified_on)}</dd>
                    </div>
                  )}
                  <ReviewBadge status={scheme?.review_status} />
                </dl>
                {target.rationale && <p className="mb-3 text-sm text-content-secondary">{target.rationale}</p>}
                <div className="mb-3 flex flex-wrap gap-2">
                  {(CERTIFICATION_ACTIONS[target.state] ?? []).map((action) => (
                    <Button
                      key={action}
                      size="sm"
                      variant={action === 'abandon' ? 'ghost' : 'secondary'}
                      {...gate(t as TFn, target, action, manage)}
                      onClick={() => setDialog({ kind: 'transition', target, action })}
                      data-testid={`certification-action-${action}`}
                    >
                      {vocab(t as TFn, CERTIFICATION_ACTION, action)}
                    </Button>
                  ))}
                  <ClosedReasons row={target} actions={targetActions(target)} skip={sharedReasons(targets, targetActions)} />
                </div>

                {target.credits.length === 0 ? (
                  <Hint testId="credits-empty">
                    {t('qualityConcept.credits.empty', {
                      defaultValue: 'No credits yet. Add the credits the team will go for, each with the points it should bring.',
                    })}
                  </Hint>
                ) : (
                  <ul className="divide-y divide-border-light" data-testid="credit-list">
                    {sharedReasons(target.credits, creditActions).length > 0 && (
                      <li>
                        <SharedReasons codes={sharedReasons(target.credits, creditActions)} />
                      </li>
                    )}
                    {target.credits.map((c) => (
                      <li key={c.id} className="py-2" data-testid="credit-entry">
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                          <span className="font-medium text-content-primary">{c.credit_code}</span>
                          {c.category && (
                            <span className="text-xs text-content-tertiary">
                              {t(`qualityConcept.creditCategory.${c.category}`, { defaultValue: humanizeCode(c.category) })}
                            </span>
                          )}
                          <StateBadge map={CREDIT_STATE} tones={CREDIT_TONE} code={c.state} />
                          <span className="text-content-secondary">
                            {t('qualityConcept.credits.points_line', {
                              defaultValue: '{{achieved}} of {{targeted}} points',
                              achieved: fmtNumber(c.points_achieved ?? '0', 1),
                              targeted: fmtNumber(c.points_targeted, 1),
                            })}
                          </span>
                          {c.owner_user_id && (
                            <span className="text-xs text-content-tertiary">
                              {personName(c.owner_user_id) ?? t('qualityConcept.common.member', { defaultValue: 'Project member' })}
                            </span>
                          )}
                          <span className="ml-auto flex flex-wrap gap-1">
                            {(CREDIT_ACTIONS[c.state] ?? []).map((action) => (
                              <Button key={action} size="sm" variant="ghost" loading={write.pending} {...gate(t as TFn, c, action)} onClick={() => runCredit(c, action)}>
                                {vocab(t as TFn, CREDIT_ACTION, action)}
                              </Button>
                            ))}
                            <Button size="sm" variant="ghost" onClick={() => setLinksOf(linksOf === c.id ? null : c.id)} aria-expanded={linksOf === c.id}>
                              {t('qualityConcept.evidence.title', { defaultValue: 'Linked records' })}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              icon={<Trash2 size={14} />}
                              aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
                              {...gate(t as TFn, c, 'delete', manage)}
                              onClick={() => setRemoving({ credit: c })}
                            />
                          </span>
                        </div>
                        <ClosedReasons row={c} actions={creditActions(c)} skip={sharedReasons(target.credits, creditActions)} />
                        {linksOf === c.id && (
                          <div className="mt-2">
                            <EvidenceLinks projectId={projectId} ownerKind="credit" ownerId={c.id} row={c} />
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-2">
                  <Button size="sm" variant="secondary" icon={<Plus size={14} />} {...gate(t as TFn, target, 'add_credits', manage)} onClick={() => setDialog({ kind: 'credit', target })} data-testid="credit-add">
                    {t('qualityConcept.credits.add', { defaultValue: 'Add credit' })}
                  </Button>
                </div>
              </Section>
            );
          })}
        </>
      )}

      {dialog?.kind === 'target' && <TargetDialog {...props} target={dialog.target} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'transition' && (
        <TransitionDialog {...props} target={dialog.target} action={dialog.action} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === 'credit' && <CreditDialog {...props} target={dialog.target} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'achieve' && <AchieveDialog {...props} credit={dialog.credit} onClose={() => setDialog(null)} />}
      <ConfirmDialog
        open={!!removing}
        variant="danger"
        loading={write.pending}
        title={
          removing?.credit
            ? t('qualityConcept.credits.remove_title', { defaultValue: 'Remove this credit?' })
            : t('qualityConcept.certification.remove_title', { defaultValue: 'Remove this certification target?' })
        }
        message={
          removing?.credit
            ? t('qualityConcept.credits.remove_body', { defaultValue: 'The credit and the links to its evidence are removed.' })
            : t('qualityConcept.certification.remove_body', { defaultValue: 'The target and all its credits are removed.' })
        }
        confirmLabel={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
        cancelLabel={t('qualityConcept.common.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const row = removing;
          setRemoving(null);
          if (row?.credit) write.send(() => deleteCredit(projectId, row.credit!.id));
          else if (row?.target) write.send(() => deleteCertification(projectId, row.target!.id));
        }}
      />
    </div>
  );
}

function TargetDialog({
  projectId,
  catalogue,
  labels,
  target,
  onClose,
}: PanelProps & { target: Certification | null; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const schemes = catalogue?.certification_schemes ?? [];
  const [pickedScheme, setScheme] = useState(target?.scheme_code ?? '');
  const schemeCode = pickedScheme || schemes[0]?.code || '';
  const scheme = schemes.find((s) => s.code === schemeCode);
  const [pickedLevel, setLevel] = useState(target?.target_level ?? '');
  const level = scheme?.levels.some((l) => l.code === pickedLevel) ? pickedLevel : (scheme?.levels[0]?.code ?? pickedLevel);
  const [scope, setScope] = useState(target?.scope ?? '');
  const [version, setVersion] = useState(target?.scheme_version ?? '');
  const [registration, setRegistration] = useState(target?.registration_no ?? '');
  const [assessor, setAssessor] = useState(target?.assessor_contact_id ?? '');
  const [certificate, setCertificate] = useState(target?.certificate_cde_id ?? '');
  const [available, setAvailable] = useState(target?.points_available ?? '');
  const availableClean = available.trim() ? pointsString(available) : '';
  const total = availableClean ? { points_available: availableClean } : {};
  const problem = !schemeCode
    ? t('qualityConcept.certification.problem_scheme', { defaultValue: 'Choose a scheme' })
    : !level
      ? t('qualityConcept.certification.problem_level', { defaultValue: 'Choose the level to aim for' })
      : availableClean === null
        ? t('qualityConcept.certification.problem_available', {
            defaultValue: 'Enter the points available as a number, or leave the field empty',
          })
        : null;

  return (
    <FormDialog
      open
      testId="certification-dialog"
      title={
        target
          ? t('qualityConcept.certification.edit_title', { defaultValue: 'Edit certification target' })
          : t('qualityConcept.certification.add', { defaultValue: 'Add certification target' })
      }
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={problem}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(
          () =>
            target
              ? patchCertification(projectId, target.id, {
                  scheme_version: version.trim(),
                  target_level: level,
                  registration_no: registration.trim(),
                  ...total,
                  ...refChange('assessor_contact_id', target.assessor_contact_id, assessor),
                  ...refChange('certificate_cde_id', target.certificate_cde_id, certificate),
                })
              : createCertification(projectId, {
                  scheme_code: schemeCode,
                  scheme_version: version.trim(),
                  scope: scope || scheme?.scope || 'building',
                  target_level: level,
                  registration_no: registration.trim(),
                  ...total,
                  ...refChange('assessor_contact_id', null, assessor),
                }),
          onClose,
        )
      }
    >
      <div className="grid gap-3 md:grid-cols-2">
        <Field required label={t('qualityConcept.certification.scheme', { defaultValue: 'Scheme' })}>
          <select
            className={inputCls}
            value={schemeCode}
            disabled={!!target}
            onChange={(e) => setScheme(e.target.value)}
            data-testid="certification-scheme"
          >
            {schemes.map((s) => (
              <option key={s.code} value={s.code}>
                {catalogueName(labels, s)}
              </option>
            ))}
          </select>
        </Field>
        <Field required label={t('qualityConcept.certification.target_level', { defaultValue: 'Target level' })}>
          <select className={inputCls} value={level} onChange={(e) => setLevel(e.target.value)} data-testid="certification-level">
            {(scheme?.levels ?? []).map((l) => (
              <option key={l.code} value={l.code}>
                {catalogueName(labels, l)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('qualityConcept.certification.scope', { defaultValue: 'Applies to' })}>
          <VocabSelect
            map={CERTIFICATION_SCOPE}
            codes={SCOPES}
            value={scope || scheme?.scope || 'building'}
            onChange={setScope}
          />
        </Field>
        <Field label={t('qualityConcept.certification.version', { defaultValue: 'Scheme version' })}>
          <input className={inputCls} value={version} onChange={(e) => setVersion(e.target.value)} />
        </Field>
        <Field label={t('qualityConcept.certification.registration_no', { defaultValue: 'Registration number' })}>
          <input className={inputCls} value={registration} onChange={(e) => setRegistration(e.target.value)} />
        </Field>
        <Field label={t('qualityConcept.certification.points_available', { defaultValue: 'Points available (optional)' })}>
          <input
            className={inputCls}
            inputMode="decimal"
            value={available}
            onChange={(e) => setAvailable(e.target.value)}
            data-testid="certification-available"
          />
        </Field>
      </div>
      <Field label={t('qualityConcept.certification.assessor', { defaultValue: 'Assessor' })}>
        <OptionPicker projectId={projectId} kind="contact" value={assessor} onChange={setAssessor} currentLabel={target?.assessor_contact_label} testId="certification-assessor" />
      </Field>
      {target && (
        <Field label={t('qualityConcept.certification.certificate', { defaultValue: 'Certificate document' })}>
          <OptionPicker projectId={projectId} kind="certificate_document" value={certificate} onChange={setCertificate} testId="certification-certificate" />
        </Field>
      )}
    </FormDialog>
  );
}

function TransitionDialog({
  projectId,
  catalogue,
  labels,
  target,
  action,
  onClose,
}: PanelProps & { target: Certification; action: CertificationAction; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const levels = catalogue?.certification_schemes.find((s) => s.code === target.scheme_code)?.levels ?? [];
  const [on, setOn] = useState('');
  const [achieved, setAchieved] = useState(action === 'certify' ? target.target_level : '');
  const [rationale, setRationale] = useState('');
  const wantsLevel = needsAchievedLevel(action);
  const wantsReason = needsRationale('certification', action);
  const problem =
    wantsLevel && !achieved
      ? t('qualityConcept.certification.problem_achieved', { defaultValue: 'Choose the level the assessor granted' })
      : wantsReason && !rationale.trim()
        ? t('qualityConcept.common.problem_reason', { defaultValue: 'Write down the reason' })
        : null;

  return (
    <FormDialog
      open
      testId="certification-transition-dialog"
      title={vocab(t as TFn, CERTIFICATION_ACTION, action)}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={problem}
      submitLabel={vocab(t as TFn, CERTIFICATION_ACTION, action)}
      onSubmit={() =>
        write.send(
          () =>
            transitionCertification(projectId, target.id, {
              action,
              achieved_level: wantsLevel ? achieved : null,
              rationale: rationale.trim(),
              on: on || null,
            }),
          onClose,
        )
      }
    >
      <div className="grid gap-3 md:grid-cols-2">
        {action !== 'abandon' && (
          <Field
            label={t('qualityConcept.common.date', { defaultValue: 'Date' })}
            hint={t('qualityConcept.common.date_today_hint', { defaultValue: 'Leave empty for today.' })}
          >
            <input type="date" className={inputCls} value={on} onChange={(e) => setOn(e.target.value)} />
          </Field>
        )}
        {wantsLevel && (
          <Field required label={t('qualityConcept.certification.achieved_level', { defaultValue: 'Level achieved' })}>
            <select className={inputCls} value={achieved} onChange={(e) => setAchieved(e.target.value)} data-testid="achieved-level">
              <option value="">{t('qualityConcept.common.choose', { defaultValue: 'Choose' })}</option>
              {levels.map((l) => (
                <option key={l.code} value={l.code}>
                  {catalogueName(labels, l)}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>
      <Field required={wantsReason} label={t('qualityConcept.common.reason', { defaultValue: 'Reason' })}>
        <textarea rows={2} className={inputCls} value={rationale} onChange={(e) => setRationale(e.target.value)} data-testid="transition-reason" />
      </Field>
    </FormDialog>
  );
}

function CreditDialog({ projectId, target, onClose }: PanelProps & { target: Certification; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [code, setCode] = useState('');
  const [category, setCategory] = useState('');
  const [points, setPoints] = useState('');
  const [owner, setOwner] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const clean = pointsString(points);
  const problem = !code.trim()
    ? t('qualityConcept.credits.problem_code', { defaultValue: 'Enter the credit code' })
    : clean === null
      ? t('qualityConcept.credits.problem_points', { defaultValue: 'Enter the targeted points as a number, zero or more' })
      : null;

  return (
    <FormDialog
      open
      testId="credit-dialog"
      title={t('qualityConcept.credits.add', { defaultValue: 'Add credit' })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={problem}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(
          () =>
            addCredits(projectId, target.id, [
              { credit_code: code.trim(), category: category.trim(), points_targeted: clean ?? '0', owner_user_id: owner || null },
            ]),
          onClose,
        )
      }
    >
      <div className="grid gap-3 md:grid-cols-2">
        <Field required label={t('qualityConcept.credits.code', { defaultValue: 'Credit code' })}>
          <input className={inputCls} value={code} onChange={(e) => setCode(e.target.value)} data-testid="credit-code" />
        </Field>
        <Field label={t('qualityConcept.credits.category', { defaultValue: 'Category' })}>
          <input className={inputCls} value={category} onChange={(e) => setCategory(e.target.value)} />
        </Field>
        <Field required label={t('qualityConcept.credits.points_targeted', { defaultValue: 'Points targeted' })}>
          <input className={inputCls} inputMode="decimal" value={points} onChange={(e) => setPoints(e.target.value)} data-testid="credit-points" />
        </Field>
        <Field label={t('qualityConcept.credits.owner', { defaultValue: 'Who looks after it' })}>
          <ProjectPeopleSelect
            projectId={projectId}
            value={owner}
            displayValue={ownerName}
            onChange={(id, name) => {
              setOwner(id);
              setOwnerName(name);
            }}
          />
        </Field>
      </div>
    </FormDialog>
  );
}

function AchieveDialog({ projectId, credit, onClose }: PanelProps & { credit: Credit; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [points, setPoints] = useState(credit.points_targeted);
  const clean = pointsString(points);

  return (
    <FormDialog
      open
      size="sm"
      testId="credit-achieve-dialog"
      title={vocab(t as TFn, CREDIT_ACTION, 'achieve')}
      subtitle={credit.credit_code}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={
        clean === null
          ? t('qualityConcept.credits.problem_achieved', { defaultValue: 'Enter the points the assessor granted' })
          : null
      }
      submitLabel={vocab(t as TFn, CREDIT_ACTION, 'achieve')}
      onSubmit={() =>
        write.send(() => patchCredit(projectId, credit.id, { action: 'achieve', points_achieved: clean ?? '0' }), onClose)
      }
    >
      <Field required label={t('qualityConcept.credits.points_achieved', { defaultValue: 'Points achieved' })}>
        <input className={inputCls} inputMode="decimal" value={points} onChange={(e) => setPoints(e.target.value)} data-testid="credit-achieved" />
      </Field>
    </FormDialog>
  );
}
