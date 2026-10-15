// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Overview tab: the facts that decide which duties apply, what those duties are,
// where each gate criterion stands and what the neighbouring modules report.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, CircleAlert, CircleHelp, TriangleAlert } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { Input } from '@/shared/ui/Input';

import {
  applyTemplates,
  approveFrame,
  consolidatePermitConditions,
  patchFrame,
  reviseFrame,
  submitFrame,
  type Catalogue,
  type Duties,
  type Frame,
  type FramePatch,
  type Readiness,
  type ReadinessState,
  type Summary,
} from './api';
import type { HseWrite } from './hooks';
import { dutyWord, labelOf, readinessDetail } from './labels';

interface Props {
  projectId: string;
  frame: Frame;
  catalogue: Catalogue;
  duties: Duties | null;
  readiness: Readiness | undefined;
  summary: Summary | undefined;
  write: HseWrite;
  canEdit: boolean;
  /** Submit, revise: the manage permission. */
  canManage: boolean;
  /** Approve: the approve permission. */
  canApprove: boolean;
}

const STATE_ICON: Record<ReadinessState, typeof CheckCircle2> = {
  met: CheckCircle2,
  warning: TriangleAlert,
  not_met: CircleAlert,
  unknown: CircleHelp,
};
const STATE_TONE: Record<ReadinessState, string> = {
  met: 'text-semantic-success',
  warning: 'text-semantic-warning',
  not_met: 'text-semantic-error',
  unknown: 'text-content-tertiary',
};

function numberOrNull(value: string): number | null {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) ? n : null;
}

function FactsForm({ projectId, frame, catalogue, write, canEdit }: Pick<Props, 'projectId' | 'frame' | 'catalogue' | 'write' | 'canEdit'>) {
  const { t, i18n } = useTranslation();
  const [draft, setDraft] = useState<FramePatch>({});
  const value = <K extends keyof FramePatch>(key: K) => (key in draft ? draft[key] : frame[key as keyof Frame]) as never;
  const set = (patch: FramePatch) => setDraft((d) => ({ ...d, ...patch }));
  const dirty = Object.keys(draft).length > 0;
  const hazardous = (value('hazardous_work_codes') as string[] | undefined) ?? [];
  const num = (key: 'duration_working_days' | 'peak_workers' | 'person_days' | 'employers_count', label: string) => (
    <Input
      label={label}
      type="number"
      min={0}
      disabled={!canEdit}
      value={(value(key) as number | null) ?? ''}
      onChange={(e) => set({ [key]: numberOrNull(e.target.value) } as FramePatch)}
      data-testid={`fact-${key}`}
    />
  );
  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="facts-form">
      <h2 className="text-sm font-semibold text-content-primary">{t('hseFrame.facts.title', { defaultValue: 'Project facts' })}</h2>
      <p className="mb-3 text-sm text-content-secondary">
        {t('hseFrame.facts.hint', {
          defaultValue: 'The catalogue decides from these figures which duties apply. A missing figure leaves the duty undecided, never waived.',
        })}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input
          label={t('hseFrame.facts.planned_start', { defaultValue: 'Planned start of construction' })}
          type="date"
          disabled={!canEdit}
          value={(value('planned_start') as string | null) ?? ''}
          onChange={(e) => set({ planned_start: e.target.value || null })}
        />
        {num('duration_working_days', t('hseFrame.facts.duration', { defaultValue: 'Duration (working days)' }))}
        {num('peak_workers', t('hseFrame.facts.peak_workers', { defaultValue: 'Peak workers on site at once' }))}
        {num('person_days', t('hseFrame.facts.person_days', { defaultValue: 'Total effort (person days)' }))}
        {num('employers_count', t('hseFrame.facts.employers', { defaultValue: 'Employers on site' }))}
        <Input
          label={t('hseFrame.facts.notice_sent', { defaultValue: 'Advance notice sent on' })}
          type="date"
          disabled={!canEdit}
          value={(value('advance_notice_sent_on') as string | null) ?? ''}
          onChange={(e) => set({ advance_notice_sent_on: e.target.value || null })}
        />
        <Input
          label={t('hseFrame.facts.notice_reference', { defaultValue: 'Advance notice reference' })}
          disabled={!canEdit}
          value={(value('advance_notice_reference') as string) ?? ''}
          onChange={(e) => set({ advance_notice_reference: e.target.value })}
        />
        <label className="flex flex-col gap-1.5 text-sm text-content-primary">
          {t('hseFrame.facts.plan_status', { defaultValue: 'Health and safety plan' })}
          <select
            className="h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm"
            disabled={!canEdit}
            value={(value('plan_status') as string) ?? 'not_started'}
            onChange={(e) => set({ plan_status: e.target.value as Frame['plan_status'] })}
            data-testid="fact-plan_status"
          >
            {(['not_started', 'draft', 'issued', 'in_force'] as const).map((s) => (
              <option key={s} value={s}>
                {t(`hseFrame.plan.${s}`, { defaultValue: s.replace('_', ' ') })}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5 text-sm text-content-primary">
          {t('hseFrame.facts.later_works', { defaultValue: 'File for later works' })}
          <select
            className="h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm"
            disabled={!canEdit}
            value={(value('later_works_status') as string) ?? 'not_started'}
            onChange={(e) => set({ later_works_status: e.target.value as Frame['later_works_status'] })}
          >
            {(['not_started', 'draft', 'complete'] as const).map((s) => (
              <option key={s} value={s}>
                {t(`hseFrame.later.${s}`, { defaultValue: s.replace('_', ' ') })}
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset className="mt-3" disabled={!canEdit}>
        <legend className="text-sm font-medium text-content-primary">
          {t('hseFrame.facts.hazardous', { defaultValue: 'Particularly hazardous works planned' })}
        </legend>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          {catalogue.hazardous_works.map((h) => (
            <label key={h.code} className="inline-flex items-center gap-1.5 text-sm text-content-primary">
              <input
                type="checkbox"
                checked={hazardous.includes(h.code)}
                onChange={(e) =>
                  set({
                    hazardous_work_codes: e.target.checked ? [...hazardous, h.code] : hazardous.filter((c) => c !== h.code),
                    hazardous_works_assessed: true,
                  })
                }
              />
              {labelOf(h, i18n.language)}
            </label>
          ))}
        </div>
        <label className="mt-2 inline-flex items-center gap-1.5 text-sm text-content-primary">
          <input
            type="checkbox"
            checked={Boolean(value('hazardous_works_assessed'))}
            onChange={(e) => set({ hazardous_works_assessed: e.target.checked })}
          />
          {t('hseFrame.facts.assessed', { defaultValue: 'The hazardous works have been assessed (none ticked means none planned)' })}
        </label>
      </fieldset>
      {canEdit && (
        <div className="mt-3 flex gap-2">
          <Button
            size="sm"
            disabled={!dirty || write.pending}
            onClick={() => write.send(() => patchFrame(projectId, draft), () => setDraft({}))}
            data-testid="facts-save"
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
          {dirty && (
            <Button size="sm" variant="ghost" onClick={() => setDraft({})}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          )}
        </div>
      )}
    </section>
  );
}

function DutyList({ duties }: { duties: Duties | null }) {
  const { t } = useTranslation();
  const rows: [keyof Duties, string][] = [
    ['advance_notice', t('hseFrame.duty.advance_notice', { defaultValue: 'Advance notice to the authority' })],
    ['coordinator', t('hseFrame.duty.coordinator', { defaultValue: 'Safety and health coordinator' })],
    ['plan', t('hseFrame.duty.plan', { defaultValue: 'Health and safety plan' })],
    ['later_works_file', t('hseFrame.duty.later_works_file', { defaultValue: 'File for later works' })],
    ['hazardous_work', t('hseFrame.duty.hazardous_work', { defaultValue: 'Particularly hazardous works' })],
  ];
  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="duty-list">
      <h2 className="text-sm font-semibold text-content-primary">{t('hseFrame.duty.title', { defaultValue: 'Duties from the facts' })}</h2>
      <ul className="mt-2 space-y-1">
        {rows.map(([key, label]) => {
          const word = dutyWord(duties ? duties[key] : null);
          return (
            <li key={key} className="flex items-center justify-between gap-3 text-sm" data-testid={`duty-${key}`} data-duty={word}>
              <span className="text-content-primary">{label}</span>
              <Badge variant={word === 'yes' ? 'warning' : word === 'no' ? 'neutral' : 'blue'}>
                {t(`hseFrame.duty.${word}`, { defaultValue: word === 'yes' ? 'Required' : word === 'no' ? 'Not required' : 'Undecided' })}
              </Badge>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function ReadinessList({ readiness, catalogue }: { readiness: Readiness | undefined; catalogue: Catalogue }) {
  const { t, i18n } = useTranslation();
  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="readiness-list">
      <h2 className="text-sm font-semibold text-content-primary">{t('hseFrame.readiness.title', { defaultValue: 'Gate readiness' })}</h2>
      <ul className="mt-2 space-y-1">
        {(readiness?.items ?? []).map((item) => {
          const Icon = STATE_ICON[item.state];
          return (
            <li key={item.code} className="flex items-start gap-2 text-sm" data-testid={`ready-${item.code}`} data-state={item.state}>
              <Icon size={14} aria-hidden className={`mt-0.5 shrink-0 ${STATE_TONE[item.state]}`} />
              <span className="text-content-primary">
                {t(`hse_frame.evidence.${item.code}`, { defaultValue: item.label })}
                {item.detail && <span className="ml-1 text-content-tertiary">({readinessDetail(item.detail, catalogue, i18n.language, t)})</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function SummaryList({ summary }: { summary: Summary | undefined }) {
  const { t } = useTranslation();
  if (!summary) return null;
  const rows: [string, number | null, string][] = [
    ['incidents_open', summary.incidents_open, t('hseFrame.summary.incidents_open', { defaultValue: 'Open incidents' })],
    ['serious_unlinked', summary.incidents_serious_open_unlinked, t('hseFrame.summary.serious_unlinked', { defaultValue: 'Serious open incidents not linked to the register' })],
    ['observations_open', summary.observations_open, t('hseFrame.summary.observations_open', { defaultValue: 'Open safety observations' })],
    ['ptw_active', summary.permits_to_work_active, t('hseFrame.summary.ptw_active', { defaultValue: 'Permits to work in force' })],
    ['capa_open', summary.corrective_actions_open, t('hseFrame.summary.capa_open', { defaultValue: 'Open corrective actions' })],
    ['audits', summary.audits, t('hseFrame.summary.audits', { defaultValue: 'Safety audits' })],
    ['inspections', summary.inspections, t('hseFrame.summary.inspections', { defaultValue: 'Inspections' })],
    ['conditions_open', summary.permit_conditions_hse_open, t('hseFrame.summary.conditions_open', { defaultValue: 'Open permit conditions on health, safety or environment' })],
    ['conditions_overdue', summary.permit_conditions_hse_overdue, t('hseFrame.summary.conditions_overdue', { defaultValue: 'Overdue permit conditions' })],
  ];
  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="summary-list">
      <h2 className="text-sm font-semibold text-content-primary">{t('hseFrame.summary.title', { defaultValue: 'From the neighbouring modules' })}</h2>
      <p className="mb-2 text-sm text-content-secondary">
        {t('hseFrame.summary.hint', { defaultValue: 'Read now from safety, HSE advanced, inspections and permits. The records stay where they are kept.' })}
      </p>
      <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {rows.map(([key, n, label]) => (
          <div key={key} className="flex justify-between gap-3 text-sm" data-testid={`summary-${key}`}>
            <dt className="text-content-secondary">{label}</dt>
            <dd className="font-medium text-content-primary">{n ?? t('hseFrame.summary.not_installed', { defaultValue: 'n/a' })}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function OverviewPanel(props: Props) {
  const { t } = useTranslation();
  const { projectId, frame, write, canEdit, canManage, canApprove } = props;
  const [note, setNote] = useState<string | null>(null);
  return (
    <div className="space-y-4" data-testid="overview-panel">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={frame.state === 'binding' || frame.state === 'approved' ? 'success' : frame.state === 'in_review' ? 'blue' : frame.state === 'revising' ? 'warning' : 'neutral'} dot>
          {t(`hseFrame.state.${frame.state}`, { defaultValue: frame.state.replace('_', ' ') })}
        </Badge>
        {canEdit && (
          <>
            <Button
              size="sm"
              variant="secondary"
              disabled={write.pending}
              onClick={() =>
                write.send(() => applyTemplates(projectId), (r) =>
                  setNote(t('hseFrame.actions.templates_done', { defaultValue: 'Rows created from the catalogue: {{n}}', n: r.created })),
                )
              }
              data-testid="apply-templates"
            >
              {t('hseFrame.actions.apply_templates', { defaultValue: 'Create rows from the catalogue' })}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={write.pending}
              onClick={() =>
                write.send(() => consolidatePermitConditions(projectId), (r) =>
                  setNote(t('hseFrame.actions.conditions_done', { defaultValue: 'Permit conditions taken over: {{n}}', n: r.created })),
                )
              }
              data-testid="consolidate-conditions"
            >
              {t('hseFrame.actions.consolidate', { defaultValue: 'Take over permit conditions' })}
            </Button>
          </>
        )}
        {canManage && (frame.state === 'draft' || frame.state === 'revising') && (
          <Button size="sm" disabled={write.pending} onClick={() => write.send(() => submitFrame(projectId))} data-testid="frame-submit">
            {t('hseFrame.actions.submit', { defaultValue: 'Submit for review' })}
          </Button>
        )}
        {canApprove && frame.state === 'in_review' && (
          <Button size="sm" disabled={write.pending} onClick={() => write.send(() => approveFrame(projectId))} data-testid="frame-approve">
            {t('hseFrame.actions.approve', { defaultValue: 'Approve' })}
          </Button>
        )}
        {canManage && (frame.state === 'in_review' || frame.state === 'approved' || frame.state === 'binding') && (
          <Button size="sm" variant="ghost" disabled={write.pending} onClick={() => write.send(() => reviseFrame(projectId))} data-testid="frame-revise">
            {t('hseFrame.actions.revise', { defaultValue: 'Revise' })}
          </Button>
        )}
      </div>
      {note && <p className="text-sm text-content-secondary" data-testid="action-note">{note}</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        <DutyList duties={props.duties} />
        <ReadinessList readiness={props.readiness} catalogue={props.catalogue} />
      </div>
      <FactsForm projectId={projectId} frame={frame} catalogue={props.catalogue} write={write} canEdit={canEdit} />
      <SummaryList summary={props.summary} />
    </div>
  );
}
