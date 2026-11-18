// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Norm-based pricing settings of a project: estimate wage, monthly hours,
// funding class, who prices the estimate and the labour location. Shown only
// when the project's country pack supplies a norm base or pricing rules; for
// every other market the server answers `available: false` and nothing renders.

import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Save } from 'lucide-react';
import { Badge, Button, Card, CardHeader } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { parseDecimalInput, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import {
  displayGrades,
  normPricingApi,
  rateDerivation,
  type EstimatePricingSettings,
  type EstimateRole,
  type PricingProfile,
} from './api';
import { NormBillActions } from './NormBillActions';

interface Draft {
  wage: string;
  hours: string;
  funding: string;
  role: '' | EstimateRole;
  location: string;
}

function draftFrom(settings: EstimatePricingSettings): Draft {
  return {
    wage: settings.estimate_wage ?? '',
    hours: settings.monthly_hours ?? '',
    funding: settings.funding_class ?? '',
    role: settings.estimate_role ?? '',
    location: settings.labour_location ?? '',
  };
}

function toBody(d: Draft): EstimatePricingSettings {
  return {
    estimate_wage: parseDecimalInput(d.wage) === null ? null : toDecimalPayloadString(d.wage),
    monthly_hours: parseDecimalInput(d.hours) === null ? null : toDecimalPayloadString(d.hours),
    funding_class: d.funding || null,
    estimate_role: d.role || null,
    labour_location: d.location || null,
  };
}

export function NormPricingCard({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const locale = i18n.language;

  const profileQuery = useQuery({
    queryKey: ['norm-pricing', 'profile', projectId, locale],
    queryFn: () => normPricingApi.profile(projectId, locale),
    staleTime: 60_000,
  });
  const profile = profileQuery.data;
  const [draft, setDraft] = useState<Draft>(() => draftFrom({}));
  useEffect(() => {
    if (profile) setDraft(draftFrom(profile.settings));
  }, [profile]);

  const grades = profile ? displayGrades(profile) : [];
  const hasWage = Boolean(profile?.settings.estimate_wage);
  const ratesQuery = useQuery({
    queryKey: ['norm-pricing', 'rates', projectId, grades.join(','), profile?.settings],
    queryFn: () => normPricingApi.labourRates(projectId, grades),
    enabled: Boolean(profile?.available && hasWage && profile.base_grade),
  });

  const saveMut = useMutation({
    mutationFn: (body: EstimatePricingSettings) => normPricingApi.saveSettings(projectId, body, locale),
    onSuccess: (next: PricingProfile) => {
      queryClient.setQueryData(['norm-pricing', 'profile', projectId, locale], next);
      queryClient.invalidateQueries({ queryKey: ['norm-pricing', 'rates', projectId] });
      addToast({ type: 'success', title: t('project.settings.saved', { defaultValue: 'Project settings saved' }) });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('project.settings.save_failed', { defaultValue: 'Failed to save settings' }),
        message: getErrorMessage(err),
      }),
  });

  if (!profile?.available) return null;

  const base = profile.norm_bases[0];
  const funding = profile.funding_classes.find((f) => f.key === draft.funding);
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    saveMut.mutate(toBody(draft));
  };

  return (
    <Card padding="lg">
      <CardHeader
        title={t('normPricing.title', { defaultValue: 'Norm-based pricing' })}
        subtitle={t('normPricing.subtitle', {
          defaultValue:
            'Hourly labour rates from the estimate wage and the grade table of {{base}}, and the markup caps of the funding type. Lines cite norm codes like {{example}}.',
          base: base?.name ?? profile.pack_slug ?? '',
          example: base?.code_example ?? '',
        })}
      />
      <form onSubmit={onSubmit} className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2" data-testid="norm-pricing-form">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="np-wage" className="oe-label">
            {t('normPricing.wage', { defaultValue: 'Estimate wage per month' })}
            {profile.currency ? ` (${profile.currency})` : ''}
          </label>
          <input
            id="np-wage"
            inputMode="decimal"
            value={draft.wage}
            onChange={(e) => setDraft({ ...draft, wage: e.target.value })}
            className="oe-input w-48"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="np-hours" className="oe-label">
            {t('normPricing.hours', { defaultValue: 'Working hours per month' })}
          </label>
          <input
            id="np-hours"
            inputMode="decimal"
            value={draft.hours}
            placeholder={profile.default_monthly_hours ?? ''}
            onChange={(e) => setDraft({ ...draft, hours: e.target.value })}
            className="oe-input w-32"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="np-funding" className="oe-label">
            {t('normPricing.funding', { defaultValue: 'Funding' })}
          </label>
          <select
            id="np-funding"
            value={draft.funding}
            onChange={(e) => setDraft({ ...draft, funding: e.target.value })}
            className="oe-input w-72"
          >
            <option value="">{t('normPricing.not_set', { defaultValue: 'Not set' })}</option>
            {profile.funding_classes.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="np-role" className="oe-label">
            {t('normPricing.role', { defaultValue: 'Who prices this estimate' })}
          </label>
          <select
            id="np-role"
            value={draft.role}
            onChange={(e) => setDraft({ ...draft, role: e.target.value as Draft['role'] })}
            className="oe-input w-72"
          >
            <option value="">{t('normPricing.not_set', { defaultValue: 'Not set' })}</option>
            <option value="investor">{t('normPricing.role_investor', { defaultValue: 'Client (investor estimate)' })}</option>
            <option value="contractor">{t('normPricing.role_contractor', { defaultValue: 'Contractor (bid price)' })}</option>
          </select>
        </div>
        {profile.location_factors.length > 0 && (
          <div className="flex flex-col gap-1.5 md:col-span-2">
            <label htmlFor="np-location" className="oe-label">
              {t('normPricing.location', { defaultValue: 'Labour location factor' })}
            </label>
            <select
              id="np-location"
              value={draft.location}
              onChange={(e) => setDraft({ ...draft, location: e.target.value })}
              className="oe-input w-96"
            >
              <option value="">{t('normPricing.location_none', { defaultValue: 'None (factor 1)' })}</option>
              {profile.location_factors.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label} × {f.factor}
                </option>
              ))}
            </select>
            <p className="text-xs text-content-tertiary md:max-w-xl">
              {t('normPricing.location_hint', {
                defaultValue:
                  'Applies to labour only. The list of territories changes by official order, so check it and set the flag yourself.',
              })}
            </p>
          </div>
        )}
        {funding && funding.markup_caps.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 md:col-span-2" data-testid="norm-pricing-caps">
            <span className="text-xs text-content-secondary">
              {t('normPricing.caps', { defaultValue: 'Caps, % of direct costs:' })}
            </span>
            {funding.markup_caps.map((c) => (
              <Badge key={c.key} variant="blue" size="sm">
                {c.label} ≤ {c.cap_percent} %
              </Badge>
            ))}
            {funding.source && <span className="text-xs text-content-tertiary">{funding.source}</span>}
          </div>
        )}
        <div className="md:col-span-2">
          <Button variant="primary" size="sm" type="submit" icon={<Save size={14} />} loading={saveMut.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </form>

      <div className="mt-5">
        <h4 className="text-sm font-medium text-content-primary">
          {t('normPricing.rates_title', { defaultValue: 'Hourly labour rates by grade' })}
        </h4>
        {!hasWage ? (
          <p className="mt-1 text-xs text-content-tertiary">
            {t('normPricing.rates_need_wage', { defaultValue: 'Enter and save the estimate wage to see the rates.' })}
          </p>
        ) : (
          <table className="mt-2 text-sm" data-testid="norm-pricing-rates">
            <thead>
              <tr className="text-left text-xs text-content-secondary">
                <th className="pr-6 font-medium">{t('normPricing.grade', { defaultValue: 'Grade' })}</th>
                <th className="pr-6 font-medium">{t('normPricing.coefficient', { defaultValue: 'Coefficient' })}</th>
                <th className="pr-6 font-medium">{t('normPricing.rate', { defaultValue: 'Rate per hour' })}</th>
                {draft.location && (
                  <th className="font-medium">{t('normPricing.rate_location', { defaultValue: 'With location factor' })}</th>
                )}
              </tr>
            </thead>
            <tbody>
              {(ratesQuery.data?.rates ?? []).map((r) => (
                <tr key={r.grade} title={ratesQuery.data ? rateDerivation(r, ratesQuery.data) : undefined}>
                  <td className="pr-6 tabular-nums">{r.grade}</td>
                  <td className="pr-6 tabular-nums">{r.coefficient}</td>
                  <td className="pr-6 tabular-nums">{r.rate}</td>
                  {draft.location && <td className="tabular-nums">{r.rate_with_location}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {profile.grading_source && (
          <p className="mt-2 text-xs text-content-tertiary md:max-w-xl" data-testid="norm-pricing-source">
            {t('normPricing.grading_source', {
              defaultValue: 'Grade coefficients: {{source}}. Hover a row to see how its rate was derived.',
              source: profile.grading_source,
            })}
          </p>
        )}
      </div>
      <NormBillActions projectId={projectId} profile={profile} />
    </Card>
  );
}
