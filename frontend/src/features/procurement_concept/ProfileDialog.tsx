// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The prequalification profile: which criteria a company is measured on, how
// much each scored one counts, and the pass mark. The criteria come from the
// pinned catalogue; the weights of the scored ones must add up to 100.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';

import { createProfile, setConcept, updateProfile, type CatalogueCriterion, type PrequalProfile } from './api';
import { catalogueName, type LabelContext } from './labels';
import { FIELD_CLASS, Field, ProblemList, RefusalBox } from './ProcurementBits';
import { PROFILE_PROBLEM, profileProblems, toProfileInput, weightsTotal, type ProfileDraft } from './rules';

export interface ProfileDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  packageId: string;
  packageCode: string;
  /** The profile being changed, or null to create one. */
  profile: PrequalProfile | null;
  criteria: CatalogueCriterion[];
  labels: LabelContext;
  onSaved: () => void;
}

export function ProfileDialog({
  open,
  onClose,
  projectId,
  packageId,
  packageCode,
  profile,
  criteria,
  labels,
  onSaved,
}: ProfileDialogProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ProfileDraft>(() => ({
    name: profile?.name ?? '',
    pass_mark: profile?.pass_mark ?? '60',
    validity_months: String(profile?.validity_months ?? 12),
    criteria: (profile?.criteria ?? []).map((c) => ({
      code: c.code,
      kind: c.kind === 'pass_fail' ? 'pass_fail' : 'scored',
      weight: c.weight,
    })),
  }));
  // Only asked when creating: a new profile serves this package, or every package without one of its own.
  const [scope, setScope] = useState<'package' | 'project'>('package');
  const problems = profileProblems(draft);
  const chosen = new Map(draft.criteria.map((c) => [c.code, c]));

  const toggle = (c: CatalogueCriterion) =>
    setDraft((d) => ({
      ...d,
      criteria: chosen.has(c.code)
        ? d.criteria.filter((x) => x.code !== c.code)
        : [...d.criteria, { code: c.code, kind: c.kind, weight: c.kind === 'scored' ? c.default_weight : '0' }],
    }));
  const setWeight = (code: string, weight: string) =>
    setDraft((d) => ({ ...d, criteria: d.criteria.map((x) => (x.code === code ? { ...x, weight } : x)) }));

  const save = useMutation({
    mutationFn: async () => {
      if (profile) return updateProfile(projectId, profile.id, toProfileInput(draft, profile.package_id));
      const created = await createProfile(projectId, toProfileInput(draft, scope === 'package' ? packageId : null));
      if (scope === 'project') await setConcept(projectId, { default_profile_id: created.id });
      return created;
    },
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="profile-dialog"
      title={
        profile
          ? t('procurement_concept.ui.profile.edit_title', { defaultValue: 'Prequalification profile' })
          : t('procurement_concept.ui.profile.new_title', { defaultValue: 'New prequalification profile' })
      }
      subtitle={t('procurement_concept.ui.profile.subtitle', {
        defaultValue: 'What a company must show before it is short-listed.',
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          <ProblemList problems={problems.map((p) => PROFILE_PROBLEM[p])} />
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('procurement_concept.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} disabled={problems.length > 0} onClick={() => save.mutate()} data-testid="profile-save">
            {t('procurement_concept.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox error={save.error} />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field className="sm:col-span-1" label={t('procurement_concept.ui.profile.name', { defaultValue: 'Name' })} htmlFor="pf-name">
            <input id="pf-name" className={FIELD_CLASS} value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
          </Field>
          <Field
            label={t('procurement_concept.ui.profile.pass_mark', { defaultValue: 'Pass mark, 0 to 100' })}
            htmlFor="pf-mark"
          >
            <input
              id="pf-mark"
              inputMode="decimal"
              className={FIELD_CLASS}
              value={draft.pass_mark}
              onChange={(e) => setDraft((d) => ({ ...d, pass_mark: e.target.value }))}
            />
          </Field>
          <Field
            label={t('procurement_concept.ui.profile.validity', { defaultValue: 'Valid for, in months' })}
            htmlFor="pf-validity"
          >
            <input
              id="pf-validity"
              inputMode="numeric"
              className={FIELD_CLASS}
              value={draft.validity_months}
              onChange={(e) => setDraft((d) => ({ ...d, validity_months: e.target.value }))}
            />
          </Field>
        </div>

        {!profile && (
          <fieldset>
            <legend className="mb-1 text-xs font-medium text-content-secondary">
              {t('procurement_concept.ui.profile.scope', { defaultValue: 'Where the profile applies' })}
            </legend>
            <label className="mr-5 inline-flex items-center gap-1.5 text-sm text-content-primary">
              <input type="radio" name="pf-scope" checked={scope === 'package'} onChange={() => setScope('package')} />
              {t('procurement_concept.ui.profile.scope_package', { defaultValue: 'Package {{code}} only', code: packageCode })}
            </label>
            <label className="inline-flex items-center gap-1.5 text-sm text-content-primary">
              <input type="radio" name="pf-scope" checked={scope === 'project'} onChange={() => setScope('project')} />
              {t('procurement_concept.ui.profile.scope_project', { defaultValue: 'Every package without a profile of its own' })}
            </label>
          </fieldset>
        )}

        <fieldset>
          <legend className="mb-2 flex w-full items-center justify-between text-xs font-medium text-content-secondary">
            <span>{t('procurement_concept.ui.profile.criteria', { defaultValue: 'Criteria' })}</span>
            <span data-testid="profile-weights-total">
              {t('procurement_concept.ui.profile.weights_total', {
                defaultValue: 'Weights add up to {{total}} of 100',
                total: weightsTotal(draft.criteria),
              })}
            </span>
          </legend>
          {criteria.length === 0 && (
            <p className="rounded-md bg-surface-secondary px-3 py-2 text-sm text-content-secondary" data-testid="profile-no-criteria">
              {t('procurement_concept.ui.profile.no_criteria', {
                defaultValue:
                  'The rule catalogue pinned to this project has no prequalification criteria, so a profile cannot be set up. Pin another catalogue on the Concept record tab, or have criteria added to this one.',
              })}
            </p>
          )}
          <ul className="space-y-1.5">
            {criteria.map((c) => {
              const picked = chosen.get(c.code);
              const name = catalogueName(labels, 'criterion', c);
              return (
                <li key={c.code} className="flex flex-wrap items-center gap-3 rounded-md border border-border-light bg-surface-elevated px-3 py-1.5" data-testid="profile-criterion">
                  <label className="flex min-w-0 flex-1 items-center gap-2 text-sm text-content-primary">
                    <input type="checkbox" checked={!!picked} onChange={() => toggle(c)} />
                    {name}
                    <span className="text-xs text-content-tertiary">
                      {c.kind === 'pass_fail'
                        ? t('procurement_concept.ui.profile.kind_pass_fail', { defaultValue: 'pass or fail' })
                        : t('procurement_concept.ui.profile.kind_scored', { defaultValue: 'scored' })}
                    </span>
                  </label>
                  {picked && c.kind === 'scored' && (
                    <input
                      inputMode="decimal"
                      aria-label={t('procurement_concept.ui.profile.weight_of', { defaultValue: 'Weight of {{name}}', name })}
                      className={`${FIELD_CLASS} w-24`}
                      value={picked.weight}
                      onChange={(e) => setWeight(c.code, e.target.value)}
                    />
                  )}
                </li>
              );
            })}
          </ul>
        </fieldset>
      </div>
    </WideModal>
  );
}
