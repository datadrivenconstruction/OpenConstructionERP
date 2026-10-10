// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The tax rate resolver working area.
 *
 * One rule governs the layout, and it is worth stating before the code
 * because every other decision here follows from it: the place a rate appears
 * is a slot, and in every case where there is no rate the slot holds no digit
 * at all. Not a dash, not a zero, not a greyed-out federal rate. Alberta
 * answering five per cent and nobody having chosen a province are the two
 * things this screen exists to keep apart, and they are kept apart by there
 * being nothing number-shaped in the second one to mistake for the first.
 *
 * `federal_rate_pct` comes back populated on the refusals as well, and it is
 * deliberately not drawn anywhere on them. It is a real figure that would be
 * standing next to an unanswered question, which is the exact failure the
 * design is here to prevent.
 */

import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { HelpCircle, FileWarning, MapPin, AlertTriangle, Landmark } from 'lucide-react';

import { ApiError } from '@/shared/lib/api';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';

import {
  listCountries,
  listSubdivisions,
  listTaxConfigsByCountry,
  resolveTaxRate,
  type TaxRateComponent,
  type TaxResolution,
} from './api';
import { PendingConfirmations } from './PendingConfirmations';
import { classifyResolution, offerableSubdivisions, type Classification } from './resolution';

const STALE = 5 * 60 * 1000;

/** The refusals the resolver raises rather than returns. */
type RefusalCode = 'multiple_replacing_rates' | 'rate_not_numeric' | 'other';

function refusalCodeOf(err: unknown): RefusalCode | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const body = err.body;
  if (body && typeof body === 'object') {
    const detail = (body as Record<string, unknown>).detail;
    if (detail && typeof detail === 'object') {
      const code = (detail as Record<string, unknown>).code;
      if (code === 'multiple_replacing_rates' || code === 'rate_not_numeric') return code;
    }
  }
  return 'other';
}

export function TaxRateResolverPanel() {
  const { t } = useTranslation();
  const [country, setCountry] = useState('');
  const [region, setRegion] = useState('');
  const [onDate, setOnDate] = useState('');
  const regionRef = useRef<HTMLSelectElement>(null);

  const countries = useQuery({
    queryKey: ['tax-rates', 'countries'],
    queryFn: () => listCountries(),
    staleTime: STALE,
  });

  const registry = useQuery({
    queryKey: ['tax-rates', 'subdivisions', country],
    queryFn: () => listSubdivisions(country),
    enabled: Boolean(country),
    staleTime: STALE,
  });

  const configs = useQuery({
    queryKey: ['tax-rates', 'configs', country],
    queryFn: () => listTaxConfigsByCountry(country),
    enabled: Boolean(country),
    staleTime: STALE,
  });

  const regions = useMemo(
    () => offerableSubdivisions(registry.data?.items ?? [], configs.data?.items ?? []),
    [registry.data, configs.data],
  );

  const resolution = useQuery({
    queryKey: ['tax-rates', 'resolve', country, region, onDate],
    queryFn: () => resolveTaxRate(country, region || null, onDate || null),
    enabled: Boolean(country),
    retry: false,
  });

  const countryLabel =
    countries.data?.items.find((c) => c.iso_code === country)?.name_en ?? country;
  const regionLabel = regions.find((r) => r.code === region)?.label ?? region;
  const jurisdiction = region ? `${countryLabel}, ${regionLabel}` : countryLabel;

  function onCountryChange(next: string) {
    setCountry(next);
    // Never carry a region across a country change. A stale CA-ON against
    // Germany would resolve to something, and what it resolved to would be
    // nobody's intention.
    setRegion('');
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-border-light bg-surface-primary p-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-sm">
            {t('tax_rates.field_country', { defaultValue: 'Country' })}
            <select
              value={country}
              onChange={(e) => onCountryChange(e.target.value)}
              className="rounded border border-border-light bg-surface-primary p-2"
              aria-label={t('tax_rates.field_country', { defaultValue: 'Country' })}
            >
              <option value="">
                {t('tax_rates.field_country_pick', { defaultValue: 'Pick a country' })}
              </option>
              {(countries.data?.items ?? []).map((c) => (
                <option key={c.iso_code} value={c.iso_code}>
                  {c.name_en}
                </option>
              ))}
            </select>
          </label>

          {regions.length > 0 && (
            <label className="flex flex-col gap-1 text-sm">
              {t('tax_rates.field_region', { defaultValue: 'Region' })}
              <select
                ref={regionRef}
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                className="rounded border border-border-light bg-surface-primary p-2"
                aria-label={t('tax_rates.field_region', { defaultValue: 'Region' })}
              >
                {/* Never preselected. A picker that defaults to the first
                    province answers a question nobody asked, with a real
                    number, which is the failure this screen is built to
                    make impossible. */}
                <option value="">
                  {t('tax_rates.field_region_none', { defaultValue: 'Not chosen yet' })}
                </option>
                {regions.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.label}
                  </option>
                ))}
              </select>
              <span className="text-2xs text-content-tertiary">
                {t('tax_rates.field_region_hint', {
                  defaultValue: 'Required: this country charges tax by region.',
                })}
              </span>
            </label>
          )}

          <label className="flex flex-col gap-1 text-sm">
            {t('tax_rates.field_date', { defaultValue: 'Priced at' })}
            <input
              type="date"
              value={onDate}
              onChange={(e) => setOnDate(e.target.value)}
              className="rounded border border-border-light bg-surface-primary p-2"
              aria-label={t('tax_rates.field_date', { defaultValue: 'Priced at' })}
            />
            <span className="text-2xs text-content-tertiary">
              {t('tax_rates.field_date_hint', {
                defaultValue: 'Rates change. A past date reads the rate that was in force then.',
              })}
            </span>
          </label>
        </div>
      </section>

      <Result
        country={country}
        jurisdiction={jurisdiction}
        countryLabel={countryLabel}
        regionLabel={regionLabel}
        query={resolution}
        onChooseRegion={() => regionRef.current?.focus()}
      />
    </div>
  );
}

interface ResultProps {
  country: string;
  jurisdiction: string;
  countryLabel: string;
  regionLabel: string;
  query: {
    data?: TaxResolution;
    error: unknown;
    isPending: boolean;
    isFetching: boolean;
    refetch: () => void;
  };
  onChooseRegion: () => void;
}

function Result({
  country,
  jurisdiction,
  countryLabel,
  regionLabel,
  query,
  onChooseRegion,
}: ResultProps) {
  const { t } = useTranslation();

  if (!country) {
    return (
      <EmptyState
        icon={<Landmark size={24} />}
        title={t('tax_rates.empty_title', { defaultValue: 'No country chosen' })}
        description={t('tax_rates.empty_body', {
          defaultValue: 'Pick a country to see the tax rate that applies to it.',
        })}
      />
    );
  }

  const refusal = refusalCodeOf(query.error);
  if (refusal) {
    return <Refused code={refusal} jurisdiction={jurisdiction} />;
  }

  if (query.error) {
    return (
      <div className="rounded-lg border border-semantic-error/40 bg-semantic-error-bg/40 p-4">
        <p className="text-sm text-content-primary">
          {t('tax_rates.load_failed', { defaultValue: 'The rate could not be looked up.' })}
        </p>
        <div className="mt-3">
          <Button variant="secondary" onClick={() => query.refetch()}>
            {t('tax_rates.retry', { defaultValue: 'Try again' })}
          </Button>
        </div>
      </div>
    );
  }

  if (query.isPending || !query.data) {
    return (
      <p className="p-4 text-sm text-content-tertiary">
        {t('tax_rates.loading', { defaultValue: 'Working out the rate' })}
      </p>
    );
  }

  const answer = classifyResolution(query.data);
  return answer.kind === 'answered' ? (
    <Answered resolution={query.data} answer={answer} jurisdiction={jurisdiction} />
  ) : (
    <Unanswered
      kind={answer.kind}
      jurisdiction={jurisdiction}
      countryLabel={countryLabel}
      regionLabel={regionLabel}
      asOf={query.data.as_of}
      onChooseRegion={onChooseRegion}
      country={country}
    />
  );
}

function Answered({
  resolution,
  answer,
  jurisdiction,
}: {
  resolution: TaxResolution;
  answer: Extract<Classification, { kind: 'answered' }>;
  jurisdiction: string;
}) {
  const { t } = useTranslation();
  const compounded = answer.components.some((c) => c.base === 'consideration_plus_federal');

  return (
    <section className="rounded-lg border border-border-light bg-surface-primary p-4">
      <div
        data-testid="tax-rates-answer-slot"
        className="flex flex-wrap items-baseline gap-x-3 gap-y-1"
      >
        <span data-testid="tax-rates-combined" className="text-4xl font-semibold text-content-primary">
          {answer.combinedRatePct}%
        </span>
        <Badge variant="success" dot>
          {statusLabel(t, resolution.status)}
        </Badge>
      </div>
      <p className="mt-1 text-sm text-content-secondary">
        {t('tax_rates.answer_caption', {
          defaultValue: 'Combined tax rate for {{jurisdiction}}',
          jurisdiction,
        })}
      </p>
      <p className="text-2xs text-content-tertiary">
        {t('tax_rates.as_of', { defaultValue: 'In force on {{date}}', date: resolution.as_of })}
      </p>

      {resolution.status === 'federal_only' && (
        <p className="mt-3 rounded border border-border-light bg-surface-secondary p-3 text-xs text-content-secondary">
          {t('tax_rates.status_federal_only_note', {
            defaultValue:
              'This region charges nothing of its own, so the federal rate is the whole answer. That is a rate, not a gap.',
          })}
        </p>
      )}

      <h3 className="mt-4 text-sm font-medium text-content-primary">
        {t('tax_rates.breakdown_title', { defaultValue: 'How this was reached' })}
      </h3>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[32rem] text-left text-xs">
          <thead className="text-content-tertiary">
            <tr>
              <th className="py-1 pr-3 font-medium">
                {t('tax_rates.col_tax', { defaultValue: 'Tax' })}
              </th>
              <th className="py-1 pr-3 font-medium">
                {t('tax_rates.col_rate', { defaultValue: 'Rate' })}
              </th>
              <th className="py-1 pr-3 font-medium">
                {t('tax_rates.col_base', { defaultValue: 'Charged on' })}
              </th>
              <th className="py-1 font-medium">
                {t('tax_rates.col_effective', { defaultValue: 'Adds to total' })}
              </th>
            </tr>
          </thead>
          <tbody className="text-content-secondary">
            {answer.components.map((c, i) => (
              <tr key={`${c.tax_code ?? c.tax_name}-${i}`} className="border-t border-border-light">
                <td className="py-1.5 pr-3">
                  <span className="text-content-primary">{c.tax_name}</span>
                  <span className="block text-2xs text-content-tertiary">
                    {combinationLabel(t, c.combination)}
                  </span>
                </td>
                <td className="py-1.5 pr-3 tabular-nums">{c.rate_pct}%</td>
                <td className="py-1.5 pr-3">{baseLabel(t, c.base)}</td>
                <td className="py-1.5 tabular-nums">{c.effective_rate_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {compounded && (
        <p className="mt-2 text-2xs text-content-tertiary">
          {t('tax_rates.compound_note', {
            defaultValue:
              'A compounded rate is charged on the amount that already includes the federal tax, so the total is more than the rates added together.',
          })}
        </p>
      )}
    </section>
  );
}

/**
 * Tone per refusal. The question is not an error and is not coloured as one.
 *
 * Keyed on the kinds themselves rather than on `string`: a kind added to the
 * classifier is then a missing property here rather than an undefined lookup
 * at the point of use, which is the difference between the compiler catching
 * it and a panel rendering with no border.
 */
const UNANSWERED_TONE: Record<
  Exclude<Classification['kind'], 'answered'>,
  { variant: 'blue' | 'warning' | 'error'; border: string }
> = {
  needs_subdivision: { variant: 'blue', border: 'border-oe-blue/40 bg-oe-blue-subtle/40' },
  subdivision_not_carried: {
    variant: 'warning',
    border: 'border-semantic-warning/40 bg-semantic-warning/5',
  },
  rates_unlabelled: {
    variant: 'warning',
    border: 'border-semantic-warning/40 bg-semantic-warning/5',
  },
  no_country_data: {
    variant: 'warning',
    border: 'border-semantic-warning/40 bg-semantic-warning/5',
  },
  rates_conflict: { variant: 'error', border: 'border-semantic-error/40 bg-semantic-error-bg/40' },
  standard_rate_not_started: {
    variant: 'warning',
    border: 'border-semantic-warning/40 bg-semantic-warning/5',
  },
  awaiting_local_confirmation: {
    variant: 'warning',
    border: 'border-semantic-warning/40 bg-semantic-warning/5',
  },
};

function Unanswered({
  kind,
  jurisdiction,
  countryLabel,
  regionLabel,
  asOf,
  onChooseRegion,
  country,
}: {
  country: string;
  kind: Exclude<Classification['kind'], 'answered'>;
  jurisdiction: string;
  countryLabel: string;
  regionLabel: string;
  asOf: string;
  onChooseRegion: () => void;
}) {
  const { t } = useTranslation();
  const tone = UNANSWERED_TONE[kind];

  // Headline and body are separate on purpose. The headline sits in the slot
  // a rate would otherwise occupy and carries no digit; anything with a date
  // or a count in it goes in the body, below the slot.
  let icon = <HelpCircle className="h-5 w-5 shrink-0 text-oe-blue" />;
  let title = '';
  let body = '';

  switch (kind) {
    case 'needs_subdivision':
      title = t('tax_rates.needs_region_title', {
        defaultValue: 'Which region is this project in?',
      });
      body = t('tax_rates.needs_region_body', {
        defaultValue:
          '{{country}} charges tax by region, so there is no one national rate to give. Choose a region and the combined rate appears here.',
        country: countryLabel,
      });
      break;
    case 'subdivision_not_carried':
      icon = <MapPin className="h-5 w-5 shrink-0 text-semantic-warning" />;
      title = t('tax_rates.region_not_carried_title', {
        defaultValue: 'No rate on file for this region',
      });
      body = t('tax_rates.region_not_carried_body', {
        defaultValue:
          'We hold no rate for {{region}} and hold no register of regions for this country, so whether it charges a tax of its own is unknown. Add its rate in the tax configuration register.',
        region: regionLabel,
      });
      break;
    case 'rates_unlabelled':
      icon = <FileWarning className="h-5 w-5 shrink-0 text-semantic-warning" />;
      title = t('tax_rates.rates_unlabelled_title', {
        defaultValue: 'The regional rates are not labelled yet',
      });
      body = t('tax_rates.rates_unlabelled_body', {
        defaultValue:
          '{{country}} has regional rates on file that do not say which region they apply in, so this cannot be answered from the data as it stands. An administrator needs to run the tax subdivision repair.',
        country: countryLabel,
      });
      break;
    case 'no_country_data':
      icon = <FileWarning className="h-5 w-5 shrink-0 text-semantic-warning" />;
      title = t('tax_rates.no_country_data_title', {
        defaultValue: 'No rates on file for this country',
      });
      body = t('tax_rates.no_country_data_body', {
        defaultValue:
          'Nothing is recorded for {{country}} on {{date}}. Add a rate in the tax configuration register.',
        country: countryLabel,
        date: asOf,
      });
      break;
    case 'rates_conflict':
      icon = <AlertTriangle className="h-5 w-5 shrink-0 text-semantic-error" />;
      title = t('tax_rates.rates_conflict_title', {
        defaultValue: 'The rates on file do not give one answer',
      });
      body = t('tax_rates.rates_conflict_body', {
        defaultValue:
          'More than one rate is in force for {{jurisdiction}} on {{date}} and none of them is marked as the standard one. Mark exactly one as the default in the tax configuration register.',
        jurisdiction,
        date: asOf,
      });
      break;
    case 'standard_rate_not_started':
      icon = <FileWarning className="h-5 w-5 shrink-0 text-semantic-warning" />;
      title = t('tax_rates.standard_rate_not_started_title', {
        defaultValue: 'The standard rate on file starts later than this date',
      });
      body = t('tax_rates.standard_rate_not_started_body', {
        defaultValue:
          'The standard rate recorded for {{jurisdiction}} begins after {{date}}. The rates in force on that date are reduced tiers, not the standard rate. Add the standard rate that applied then, with its own dates.',
        jurisdiction,
        date: asOf,
      });
      break;
    case 'awaiting_local_confirmation':
      icon = <FileWarning className="h-5 w-5 shrink-0 text-semantic-warning" />;
      title = t('tax_rates.awaiting_confirmation_title', {
        defaultValue: 'Not yet confirmed by a local specialist',
      });
      body = t('tax_rates.awaiting_confirmation_body', {
        defaultValue:
          'A rate in force for {{jurisdiction}} on {{date}} has to be confirmed by a local specialist, usually your accountant, against the tax authority\'s own publication. It is not used until then.',
        jurisdiction,
        date: asOf,
      });
      break;
  }

  return (
    <section
      data-testid="tax-rates-unanswered"
      data-kind={kind}
      className={`rounded-lg border p-4 ${tone.border}`}
    >
      <div data-testid="tax-rates-answer-slot" className="flex items-start gap-2">
        {icon}
        <h3 className="text-lg font-semibold text-content-primary">{title}</h3>
      </div>
      <p className="mt-2 text-sm text-content-secondary">{body}</p>
      <p className="mt-2 text-2xs text-content-tertiary">
        {t('tax_rates.no_number_note', {
          defaultValue:
            'No figure is shown here on purpose. A plausible rate is worse than none: it reads exactly like a correct one and travels into a tender.',
        })}
      </p>
      {kind === 'awaiting_local_confirmation' && <PendingConfirmations country={country} />}
      {kind === 'needs_subdivision' && (
        <div className="mt-3">
          <Button variant="primary" onClick={onChooseRegion}>
            {t('tax_rates.needs_region_action', { defaultValue: 'Choose a region' })}
          </Button>
        </div>
      )}
    </section>
  );
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

function statusLabel(t: Translate, status: TaxResolution['status']): string {
  switch (status) {
    case 'harmonised':
      return t('tax_rates.status_harmonised', { defaultValue: 'Harmonised' });
    case 'stacked':
      return t('tax_rates.status_stacked', { defaultValue: 'Federal plus regional' });
    case 'compounded':
      return t('tax_rates.status_compounded', { defaultValue: 'Compounded' });
    case 'federal_only':
      return t('tax_rates.status_federal_only', { defaultValue: 'Federal only' });
    default:
      return t('tax_rates.status_national', { defaultValue: 'National' });
  }
}

function combinationLabel(t: Translate, combination: TaxRateComponent['combination']): string {
  switch (combination) {
    case 'replaces_federal':
      return t('tax_rates.combination_replaces_federal', {
        defaultValue: 'Replaces the federal rate',
      });
    case 'stacks_on_federal':
      return t('tax_rates.combination_stacks_on_federal', {
        defaultValue: 'Stacks on the federal rate',
      });
    case 'compounds_on_federal':
      return t('tax_rates.combination_compounds_on_federal', {
        defaultValue: 'Compounds on the federal rate',
      });
    case 'federal':
      return t('tax_rates.combination_federal', { defaultValue: 'Federal rate' });
    default:
      return t('tax_rates.combination_national', { defaultValue: 'National rate' });
  }
}

function baseLabel(t: Translate, base: TaxRateComponent['base']): string {
  return base === 'consideration_plus_federal'
    ? t('tax_rates.base_plus_federal', { defaultValue: 'the federal-inclusive amount' })
    : t('tax_rates.base_consideration', { defaultValue: 'the pre-tax amount' });
}

function Refused({ code, jurisdiction }: { code: RefusalCode; jurisdiction: string }) {
  const { t } = useTranslation();

  let title = t('tax_rates.refused_other_title', {
    defaultValue: 'The rate could not be worked out',
  });
  let body = t('tax_rates.refused_other_body', {
    defaultValue:
      'The rates recorded for {{jurisdiction}} could not be combined. Check them in the tax configuration register.',
    jurisdiction,
  });

  if (code === 'multiple_replacing_rates') {
    title = t('tax_rates.refused_multiple_replacing_title', {
      defaultValue: 'Two rates both replace the federal one',
    });
    body = t('tax_rates.refused_multiple_replacing_body', {
      defaultValue:
        'More than one rate for {{jurisdiction}} claims to replace the federal rate. Only one can. Close the date window on the one that has ended.',
      jurisdiction,
    });
  } else if (code === 'rate_not_numeric') {
    title = t('tax_rates.refused_rate_not_numeric_title', {
      defaultValue: 'A rate on file is not a number',
    });
    body = t('tax_rates.refused_rate_not_numeric_body', {
      defaultValue:
        'One of the rates recorded for {{jurisdiction}} cannot be read as a number, so the total cannot be worked out. Correct it in the tax configuration register.',
      jurisdiction,
    });
  }

  return (
    <section
      data-testid="tax-rates-unanswered"
      data-kind="refused"
      className="rounded-lg border border-semantic-error/40 bg-semantic-error-bg/40 p-4"
    >
      <div data-testid="tax-rates-answer-slot" className="flex items-start gap-2">
        <AlertTriangle className="h-5 w-5 shrink-0 text-semantic-error" />
        <h3 className="text-lg font-semibold text-content-primary">{title}</h3>
      </div>
      <p className="mt-2 text-sm text-content-secondary">{body}</p>
      <p className="mt-2 text-2xs text-content-tertiary">
        {t('tax_rates.no_number_note', {
          defaultValue:
            'No figure is shown here on purpose. A plausible rate is worse than none: it reads exactly like a correct one and travels into a tender.',
        })}
      </p>
    </section>
  );
}
