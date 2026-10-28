// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One stakeholder: what they care about, how they are classified, and every
// assessment made so far, newest first. Assessing is the one primary action;
// an assessment is added, never changed, so the history shows how the view of
// this stakeholder moved over time.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ClipboardCheck, Pencil } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import { archiveStakeholder, type Stakeholder } from './api';
import { ATTITUDE, AssessmentDialog } from './AssessmentDialog';
import { classificationName } from './RegisterPanel';
import { GatedButton, STAKEHOLDER_TONE, ToneBadge, useWrite } from './StakeholderBits';
import { StakeholderDialog } from './StakeholderDialog';
import { useAssessments } from './hooks';
import { STAKEHOLDER_STATUS, itemName, nameOf, vocab, type TFn } from './labels';
import { stakeholderName, type Screen } from './screen';

export interface StakeholderDetailProps {
  screen: Screen;
  stakeholder: Stakeholder;
  /** The register, for the group this stakeholder belongs to and what belongs to it. */
  stakeholders: Stakeholder[];
  onBack: () => void;
}

export function StakeholderDetail({ screen, stakeholder, stakeholders, onBack }: StakeholderDetailProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels, personName, onChanged } = screen;
  const fw = settings.framework;
  const assessmentsQ = useAssessments(projectId, stakeholder.id);
  const [dialog, setDialog] = useState<'assess' | 'edit' | 'archive' | null>(null);

  const archive = useWrite(
    () => archiveStakeholder(projectId, stakeholder.id),
    () => {
      setDialog(null);
      onChanged();
      onBack();
    },
  );

  const assessments = assessmentsQ.data ?? [];
  const parent = stakeholders.find((s) => s.id === stakeholder.parent_stakeholder_id) ?? null;
  const members = stakeholders.filter((s) => s.parent_stakeholder_id === stakeholder.id && s.status !== 'archived');
  const facts: Array<[string, string]> = [
    [t('stakeholders.ui.stakeholder.interests', { defaultValue: 'What they care about' }), stakeholder.interests],
    [
      t('stakeholders.ui.stakeholder.expectations', { defaultValue: 'What they expect from the project' }),
      stakeholder.expectations,
    ],
    [t('stakeholders.ui.stakeholder.concerns', { defaultValue: 'What worries them' }), stakeholder.concerns],
    [t('stakeholders.ui.stakeholder.address', { defaultValue: 'Address' }), stakeholder.geo?.address ?? ''],
    [t('stakeholders.ui.stakeholder.parcel', { defaultValue: 'Land parcel' }), stakeholder.geo?.parcel_ref ?? ''],
    [
      t('stakeholders.ui.stakeholder.position', { defaultValue: 'Position' }),
      stakeholder.geo?.lat && stakeholder.geo?.lon
        ? t('stakeholders.ui.stakeholder.position_value', {
            defaultValue: '{{lat}}, {{lon}}',
            lat: stakeholder.geo.lat,
            lon: stakeholder.geo.lon,
          })
        : '',
    ],
  ];

  return (
    <div className="space-y-5" data-testid="stakeholder-detail">
      <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} />} onClick={onBack}>
        {t('stakeholders.ui.back_to_register', { defaultValue: 'Back to the register' })}
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-content-primary">{stakeholderName(t, stakeholder)}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
            <span>{stakeholder.code}</span>
            <span>{nameOf(labels, fw.stakeholder_categories, stakeholder.category)}</span>
            <ToneBadge tone={STAKEHOLDER_TONE[stakeholder.status]}>{vocab(t, STAKEHOLDER_STATUS, stakeholder.status)}</ToneBadge>
            {stakeholder.is_group && (
              <span>
                {stakeholder.group_size_estimate != null
                  ? t('stakeholders.ui.stakeholder.group_of', {
                      defaultValue: 'Group of about {{size}}',
                      size: stakeholder.group_size_estimate,
                    })
                  : t('stakeholders.ui.stakeholder.group', { defaultValue: 'Group' })}
              </span>
            )}
            {parent && (
              <span data-testid="stakeholder-parent-line">
                {t('stakeholders.ui.stakeholder.part_of', {
                  defaultValue: 'Part of {{name}}',
                  name: stakeholderName(t, parent),
                })}
              </span>
            )}
          </div>
          {members.length > 0 && (
            <p className="mt-1 text-xs text-content-secondary" data-testid="stakeholder-members-line">
              {t('stakeholders.ui.stakeholder.includes', {
                defaultValue: 'Includes {{names}}',
                names: fmtList(members.map((m) => stakeholderName(t, m))),
              })}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <GatedButton
            allowed={settings.can.edit}
            capability="edit"
            icon={<ClipboardCheck size={14} />}
            disabled={stakeholder.status === 'archived'}
            onClick={() => setDialog('assess')}
            data-testid="stakeholder-assess"
          >
            {t('stakeholders.ui.assessment.title', { defaultValue: 'Assess stakeholder' })}
          </GatedButton>
          {settings.can.edit && (
            <>
              <Button variant="secondary" icon={<Pencil size={14} />} onClick={() => setDialog('edit')} data-testid="stakeholder-edit">
                {t('stakeholders.ui.edit', { defaultValue: 'Edit' })}
              </Button>
              {stakeholder.status !== 'archived' && (
                <Button variant="ghost" onClick={() => setDialog('archive')} data-testid="stakeholder-archive">
                  {t('stakeholders.ui.stakeholder.archive', { defaultValue: 'Archive' })}
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label={t('stakeholders.ui.register.col_class', { defaultValue: 'Classification' })}>
          {classificationName(labels, settings, stakeholder)}
        </Fact>
        <Fact label={t('stakeholders.ui.assessment.current', { defaultValue: 'Today' })}>
          {stakeholder.engagement_current
            ? nameOf(labels, fw.engagement_levels, stakeholder.engagement_current)
            : t('stakeholders.ui.not_set', { defaultValue: 'Not set' })}
        </Fact>
        <Fact label={t('stakeholders.ui.assessment.desired', { defaultValue: 'Needed' })}>
          {stakeholder.engagement_desired
            ? nameOf(labels, fw.engagement_levels, stakeholder.engagement_desired)
            : t('stakeholders.ui.not_set', { defaultValue: 'Not set' })}
        </Fact>
        <Fact label={t('stakeholders.ui.register.col_owner', { defaultValue: 'Relationship kept by' })}>
          {personName(stakeholder.relationship_owner_user_id) ?? t('stakeholders.ui.nobody', { defaultValue: 'Nobody yet' })}
        </Fact>
      </dl>

      {facts.some(([, text]) => text) && (
        <dl className="grid gap-3 sm:grid-cols-3">
          {facts
            .filter(([, text]) => text)
            .map(([label, text]) => (
              <Fact key={label} label={label}>
                <span className="whitespace-pre-line font-normal">{text}</span>
              </Fact>
            ))}
        </dl>
      )}

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('stakeholders.ui.assessment.history', { defaultValue: 'Assessment history' })}
        </h3>
        {assessmentsQ.isLoading ? (
          <SkeletonTable rows={2} columns={4} />
        ) : assessmentsQ.isError ? (
          <ErrorState
            compact
            title={t('stakeholders.ui.assessment.load_failed', { defaultValue: 'The assessments could not be loaded' })}
            hint={getErrorMessage(assessmentsQ.error)}
            onRetry={() => assessmentsQ.refetch()}
          />
        ) : assessments.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-secondary" data-testid="assessments-empty">
            {t('stakeholders.ui.assessment.empty', {
              defaultValue: 'Not assessed yet. An assessment says how much this stakeholder can affect the project and how engaged they need to be.',
            })}
          </p>
        ) : (
          <ul className="space-y-2" data-testid="assessment-history">
            {assessments.map((a) => {
              const method = fw.analysis_methods.find((m) => m.code === a.method_code);
              const scoreParts = Object.entries(a.scores).map(([code, value]) =>
                scoreText(t as TFn, nameOf(labels, method?.dimensions ?? [], code), value),
              );
              return (
                <li key={a.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="assessment-entry">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
                    <span className="text-sm font-medium text-content-primary">
                      {a.classification ? nameOf(labels, method?.classes ?? [], a.classification) : t('stakeholders.ui.unclassified', { defaultValue: 'Unclassified' })}
                    </span>
                    <span>{method ? itemName(labels, method) : a.method_code}</span>
                    <span className="ml-auto flex gap-2">
                      {a.assessed_at && <span>{fmtDate(a.assessed_at)}</span>}
                      {personName(a.assessed_by) && <span>{personName(a.assessed_by)}</span>}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-content-secondary">{fmtList(scoreParts)}</p>
                  {a.attitude != null && ATTITUDE[String(a.attitude)] && (
                    <p className="text-xs text-content-secondary">
                      {t('stakeholders.ui.assessment.attitude_line', {
                        defaultValue: 'Attitude to the project: {{attitude}}',
                        attitude: t(ATTITUDE[String(a.attitude)]![0], { defaultValue: ATTITUDE[String(a.attitude)]![1] }),
                      })}
                    </p>
                  )}
                  {a.rationale && <p className="mt-1 whitespace-pre-line text-sm text-content-primary">{a.rationale}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {dialog === 'assess' && (
        <AssessmentDialog
          screen={screen}
          stakeholder={stakeholder}
          previous={assessments[0] ?? null}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            onChanged();
          }}
        />
      )}
      {dialog === 'edit' && (
        <StakeholderDialog
          screen={screen}
          stakeholder={stakeholder}
          stakeholders={stakeholders}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            onChanged();
          }}
        />
      )}
      <ConfirmDialog
        open={dialog === 'archive'}
        variant="warning"
        loading={archive.busy}
        title={t('stakeholders.ui.stakeholder.archive_title', { defaultValue: 'Archive this stakeholder?' })}
        message={
          archive.refusal?.message ??
          t('stakeholders.ui.stakeholder.archive_body', {
            defaultValue: 'The stakeholder leaves the register. Assessments and commitments stay on record and keep pointing at it.',
          })
        }
        confirmLabel={t('stakeholders.ui.stakeholder.archive', { defaultValue: 'Archive' })}
        cancelLabel={t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => {
          archive.clear();
          setDialog(null);
        }}
        onConfirm={() => archive.run(undefined)}
      />
    </div>
  );
}

/** One score in words: "Power 4", or just the scale name for a yes on a yes/no scale. */
function scoreText(t: TFn, name: string, value: number | boolean): string {
  if (typeof value === 'boolean') {
    return value
      ? t('stakeholders.ui.assessment.score_yes', { defaultValue: '{{name}}: yes', name })
      : t('stakeholders.ui.assessment.score_no', { defaultValue: '{{name}}: no', name });
  }
  return t('stakeholders.ui.assessment.score_value', { defaultValue: '{{name}} {{value}}', name, value });
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
      <dt className="text-xs text-content-tertiary">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-content-primary">{children}</dd>
    </div>
  );
}
