// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Payment terms beside a contract's retention rate, and where each one came from.
 *
 * A contract starts from the usual terms of its project's country: retention
 * and its cap, how retention is paid back, the payment period, the valuation
 * rhythm and the name of the interim certificate. The figures themselves live
 * on the server (one table, `contracts/country_defaults.py`), so nothing here
 * knows a country. This file only names things and says, beside a figure the
 * country filled in, that it is that country's default and what it rests on.
 */

import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { fmtList } from '@/shared/lib/formatters';
import {
  getContractCountryDefaults,
  type ContractDefaultsStamp,
  type ContractItem,
  type ContractPaymentTerms,
  type CountryDefaultField,
  type CountryDefaultSource,
  type ReleaseSplitStep,
  type ValuationInterval,
} from './api';
import { retentionEventLabel } from './RetentionReleasePanel';

// The two readers live here rather than in ./api, which several drawer tests
// replace wholesale with an explicit list of mocked calls: a plain function
// over the contract has nothing to mock and should not have to be listed.

/** The payment terms a contract states (`terms.payment_terms`), `{}` when it states none. */
export function paymentTermsOf(contract: Pick<ContractItem, 'terms'>): ContractPaymentTerms {
  const block = contract.terms?.payment_terms;
  return block && typeof block === 'object' ? (block as ContractPaymentTerms) : {};
}

/** What the contract recorded about the country defaults it was created from, or null. */
export function defaultsStampOf(
  contract: Pick<ContractItem, 'metadata'>,
): ContractDefaultsStamp | null {
  const stamp = contract.metadata?.country_defaults;
  if (!stamp || typeof stamp !== 'object') return null;
  const s = stamp as Partial<ContractDefaultsStamp>;
  return {
    country_code: s.country_code ?? null,
    has_country_defaults: Boolean(s.has_country_defaults),
    applied: s.applied && typeof s.applied === 'object' ? s.applied : {},
    sources: s.sources && typeof s.sources === 'object' ? s.sources : {},
    release_split_source: s.release_split_source ?? null,
    fallback: Array.isArray(s.fallback) ? s.fallback : [],
  };
}

export const VALUATION_INTERVALS: ValuationInterval[] = [
  'monthly',
  'four_weekly',
  'fortnightly',
  'weekly',
  'milestone',
];

const INTERVAL_LABELS: Record<ValuationInterval, string> = {
  monthly: 'Monthly',
  four_weekly: 'Every four weeks',
  fortnightly: 'Every two weeks',
  weekly: 'Weekly',
  milestone: 'At milestones',
};

export function valuationIntervalLabel(t: TFunction, value: string): string {
  return t(`contracts.payment_terms.interval.${value}`, {
    defaultValue: INTERVAL_LABELS[value as ValuationInterval] ?? value.replace(/_/g, ' '),
  });
}

/**
 * The release patterns a person picks from. Percentages are of what is held
 * AT each event, which is why "half, then the rest" ends on 100 and not 50.
 */
export interface ReleaseSplitPreset {
  id: string;
  split: ReleaseSplitStep[];
  defaultLabel: string;
}

export const RELEASE_SPLIT_PRESETS: ReleaseSplitPreset[] = [
  {
    id: 'sc50_dpe100',
    split: [
      { event: 'substantial_completion', release_percent_of_held: '50' },
      { event: 'defects_period_end', release_percent_of_held: '100' },
    ],
    defaultLabel: 'Half at completion, the rest at the end of the defects period',
  },
  {
    id: 'sc100',
    split: [{ event: 'substantial_completion', release_percent_of_held: '100' }],
    defaultLabel: 'All at completion',
  },
  {
    id: 'dpe100',
    split: [{ event: 'defects_period_end', release_percent_of_held: '100' }],
    defaultLabel: 'All at the end of the defects period',
  },
  {
    id: 'fc100',
    split: [{ event: 'final_completion', release_percent_of_held: '100' }],
    defaultLabel: 'All at final completion',
  },
  {
    id: 'sc100_fc100',
    split: [
      { event: 'substantial_completion', release_percent_of_held: '100' },
      { event: 'final_completion', release_percent_of_held: '100' },
    ],
    defaultLabel: 'At completion, anything held back at final completion',
  },
  {
    id: 'sc100_dpe100',
    split: [
      { event: 'substantial_completion', release_percent_of_held: '100' },
      { event: 'defects_period_end', release_percent_of_held: '100' },
    ],
    defaultLabel: 'At completion against a defects security, that security at the end of the defects period',
  },
];

function samePercent(a: string, b: string): boolean {
  const x = Number(a);
  const y = Number(b);
  return Number.isFinite(x) && Number.isFinite(y) ? x === y : a === b;
}

/** The preset a split matches, or null for a split no preset describes. */
export function splitPresetId(split: ReleaseSplitStep[] | null | undefined): string | null {
  if (!split || split.length === 0) return null;
  const match = RELEASE_SPLIT_PRESETS.find(
    (preset) =>
      preset.split.length === split.length &&
      preset.split.every((step, index) => {
        const other = split[index];
        return (
          other !== undefined &&
          other.event === step.event &&
          samePercent(other.release_percent_of_held, step.release_percent_of_held)
        );
      }),
  );
  return match ? match.id : null;
}

export function releaseSplitText(t: TFunction, split: ReleaseSplitStep[] | null | undefined): string {
  if (!split || split.length === 0) {
    return t('contracts.payment_terms.not_stated', { defaultValue: 'Not stated' });
  }
  const preset = RELEASE_SPLIT_PRESETS.find((p) => p.id === splitPresetId(split));
  if (preset) {
    return t(`contracts.payment_terms.split.${preset.id}`, { defaultValue: preset.defaultLabel });
  }
  return fmtList(
    split.map((step) =>
      t('contracts.payment_terms.split_step', {
        defaultValue: '{{percent}}% of what is held at {{event}}',
        percent: step.release_percent_of_held,
        event: retentionEventLabel(t, step.event),
      }),
    ),
  );
}

/** A country's name in the reader's language, or its code where the browser has none. */
export function countryName(code: string | null | undefined, language: string): string {
  if (!code) return '';
  try {
    const names = new Intl.DisplayNames([language || 'en'], { type: 'region' });
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

const SOURCE_LABELS: Record<string, string> = {
  statute: 'Statute',
  standard_form: 'Standard contract form',
  industry_practice: 'Usual practice',
  regional_pack: 'Regional pack',
};

/**
 * What a default rests on, for the tooltip: the kind of source, the
 * reference as written (a clause or a law is data) and the note in the
 * reader's language. The server sends the note in English; the locale files
 * carry it under `contracts.country_defaults.<CC>.<field>.note`, and the
 * server's English is only the fallback.
 */
export function sourceTitle(
  t: TFunction,
  source: CountryDefaultSource | undefined,
  country: string,
  field: CountryDefaultField,
): string | undefined {
  if (!source) return undefined;
  const kind = t(`contracts.payment_terms.source.${source.source}`, {
    defaultValue: SOURCE_LABELS[source.source] ?? source.source,
  });
  const note = source.note
    ? t(source.note_key ?? `contracts.country_defaults.${country}.${field}.note`, {
        defaultValue: source.note,
      })
    : '';
  return [kind, source.reference, note].filter(Boolean).join(' · ');
}

/**
 * "Default for Germany" under a field the country filled in, with what it
 * rests on in the tooltip. Renders nothing when the figure is not a default.
 *
 * `noteField` names the table figure whose note explains the value when that
 * is not `field` itself: a subcontract's rate held to the country's cap is
 * explained by the cap's note.
 */
export function DefaultHint({
  field,
  noteField,
  country,
  source,
  testId,
}: {
  field: CountryDefaultField;
  noteField?: CountryDefaultField;
  country: string | null | undefined;
  source: CountryDefaultSource | undefined;
  testId?: string;
}) {
  const { t, i18n } = useTranslation();
  if (!country) return null;
  return (
    <p
      className="mt-1 text-xs text-content-tertiary"
      title={sourceTitle(t, source, country, noteField ?? field)}
      data-testid={testId ?? `default-hint-${field}`}
    >
      {t('contracts.payment_terms.default_for', {
        defaultValue: 'Default for {{country}}',
        country: countryName(country, i18n.language),
      })}
      {source?.reference ? ` · ${source.reference}` : ''}
    </p>
  );
}

export function countryDefaultsQueryKey(projectId: string) {
  return ['contracts', 'country-defaults', projectId] as const;
}

/** What a new contract on the project starts from. Cached long: the table changes with releases. */
export function useContractCountryDefaults(projectId: string) {
  return useQuery({
    queryKey: countryDefaultsQueryKey(projectId),
    queryFn: () => getContractCountryDefaults(projectId),
    enabled: Boolean(projectId),
    staleTime: 60 * 60 * 1000,
  });
}

function Row({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: ReactNode;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
      {hint}
    </div>
  );
}

/**
 * The payment terms on a contract, read-only, each marked when the project's
 * country filled it in. A retention rate that is the platform's fallback is
 * said out loud, because it is nobody's law and someone should check it.
 */
export function ContractPaymentTermsSummary({ contract }: { contract: ContractItem }) {
  const { t } = useTranslation();
  const terms = paymentTermsOf(contract);
  const stamp = defaultsStampOf(contract);
  const applied: ContractDefaultsStamp['applied'] = stamp?.applied ?? {};
  const country = stamp?.country_code ?? null;
  const hint = (field: CountryDefaultField) =>
    field in applied ? (
      <DefaultHint field={field} country={country} source={stamp?.sources[field]} />
    ) : null;
  const split =
    terms.retention_release_split ??
    (stamp?.release_split_source === 'regional_pack'
      ? (applied.retention_release_split as ReleaseSplitStep[] | undefined)
      : undefined);
  const notStated = t('contracts.payment_terms.not_stated', { defaultValue: 'Not stated' });
  const fallback = stamp?.fallback ?? [];

  return (
    <div data-testid="contract-payment-terms">
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        {'retention_percent' in applied && (
          <Row
            label={t('contracts.payment_terms.retention_rate', { defaultValue: 'Retention rate' })}
            value={`${contract.retention_percent}%`}
            hint={hint('retention_percent')}
          />
        )}
        <Row
          label={t('contracts.payment_terms.retention_cap', {
            defaultValue: 'Retention cap (% of contract sum)',
          })}
          value={
            terms.retention_cap_percent
              ? `${terms.retention_cap_percent}%`
              : t('contracts.payment_terms.no_cap', { defaultValue: 'No cap' })
          }
          hint={hint('retention_cap_percent')}
        />
        <Row
          label={t('contracts.payment_terms.release_split', { defaultValue: 'Retention release' })}
          value={releaseSplitText(t, split)}
          hint={hint('retention_release_split')}
        />
        <Row
          label={t('contracts.payment_terms.payment_period_days', {
            defaultValue: 'Payment period (days)',
          })}
          value={
            terms.payment_period_days != null ? String(terms.payment_period_days) : notStated
          }
          hint={hint('payment_period_days')}
        />
        <Row
          label={t('contracts.payment_terms.valuation_interval', {
            defaultValue: 'Valuation interval',
          })}
          value={
            terms.valuation_interval
              ? valuationIntervalLabel(t, terms.valuation_interval)
              : notStated
          }
          hint={hint('valuation_interval')}
        />
        <Row
          label={t('contracts.payment_terms.certificate_name', {
            defaultValue: 'Interim certificate',
          })}
          value={terms.certificate_name || notStated}
          hint={hint('certificate_name')}
        />
      </div>
      {fallback.includes('retention_percent') && (
        <p
          className="mt-3 flex items-start gap-1.5 text-xs text-semantic-warning"
          data-testid="retention-fallback-warning"
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          {t('contracts.payment_terms.fallback_warning', {
            defaultValue:
              "The retention rate is the platform's fallback, not a usual figure for this project's country. Check it against the contract.",
          })}
        </p>
      )}
    </div>
  );
}
