// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tax Withholding — what a payment to a subcontractor actually pays out.
 *
 * The module answers one question and the screen is arranged around it: given
 * a gross amount and who is being paid, what is withheld and what is left. The
 * preview leads because that answer is wanted *before* the payment is agreed,
 * which is why the backend keeps it separate from recording a deduction and
 * stores nothing when it is asked.
 *
 * The two things the preview reports beyond the figure carry the point of the
 * module. `band_downgraded_from` says the band asked for could not be used —
 * an expired or missing verification quietly dropping a party to the scheme's
 * default, highest-rate band is the surprise this exists to prevent — and
 * `below_threshold` says the payment is under an exemption limit that is
 * normally annual, so one payment cannot settle it.
 *
 * **Nothing here is project-scoped, deliberately.** A scheme is national
 * reference data and a party's standing under it is company-wide: a
 * subcontractor is verified once, not once per job. Only deductions and
 * reverse-charge determinations sit on a project, and neither is on this
 * screen, so there is no active-project guard.
 *
 * **What is deliberately left out.** Recording and editing deductions, and
 * reverse-charge determinations. Both are full write surfaces with their own
 * validation-blocks-the-save behaviour (an ERROR finding stops a deduction
 * leaving draft), and a half-built form over a figure that is filed with a tax
 * authority is worse than no form. The read side and the preview are complete.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { BadgeCheck, Calculator, Download, Landmark, ShieldAlert } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { formatCurrency } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { useToastStore } from '@/stores/useToastStore';

import {
  type DeductionPreview,
  type PartyStatus,
  type Regime,
  listExpiringPartyStatuses,
  listPartyStatuses,
  listRegimes,
  previewDeduction,
  seedRegimes,
} from './api';
import { type StandingState, bandRate, findBand, standingState, standingVariant } from './withholdingStatus';

/** The window the expiring list asks about, and the one the badges agree with. */
const EXPIRY_WINDOW_DAYS = 60;

/**
 * The badge each standing state wears.
 *
 * Written as static keys rather than composed from the state at the call site,
 * so a scan for a key in this repository finds all six of them.
 */
const STATE_LABEL: Record<StandingState, { key: string; en: string }> = {
  revoked: { key: 'tax_withholding.state_revoked', en: 'Revoked' },
  lapsed: { key: 'tax_withholding.state_lapsed', en: 'Lapsed' },
  unverified: { key: 'tax_withholding.state_unverified', en: 'No verification reference' },
  pending: { key: 'tax_withholding.state_pending', en: 'Recorded, not confirmed' },
  not_yet: { key: 'tax_withholding.state_not_yet', en: 'Not started yet' },
  expiring: { key: 'tax_withholding.state_expiring', en: 'Running out' },
  current: { key: 'tax_withholding.state_current', en: 'Current' },
};

export function TaxWithholdingPanel() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const regimesQuery = useQuery({
    queryKey: ['tax-withholding', 'regimes'],
    queryFn: () => listRegimes(),
    staleTime: 5 * 60 * 1000,
  });

  const standingsQuery = useQuery({
    queryKey: ['tax-withholding', 'party-status'],
    queryFn: () => listPartyStatuses(),
  });

  const expiringQuery = useQuery({
    queryKey: ['tax-withholding', 'party-status', 'expiring', EXPIRY_WINDOW_DAYS],
    queryFn: () => listExpiringPartyStatuses(EXPIRY_WINDOW_DAYS),
  });

  const seed = useMutation({
    mutationFn: seedRegimes,
    onSuccess: (result) => {
      addToast({
        type: 'success',
        title: t('tax_withholding.seeded', { defaultValue: 'Shipped schemes installed' }),
        // Interpolation variables, never a template literal: a language that
        // orders these two counts differently has to be able to.
        message: t('tax_withholding.seeded_counts', {
          defaultValue: '{{created}} added, {{existing}} already on file and left untouched.',
          created: result.created,
          existing: result.existing,
        }),
      });
      void queryClient.invalidateQueries({ queryKey: ['tax-withholding'] });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('tax_withholding.seed_failed', { defaultValue: 'Could not install the schemes' }),
        message: getErrorMessage(err),
      });
    },
  });

  const regimes = regimesQuery.data ?? [];
  const standings = standingsQuery.data ?? [];
  const expiring = expiringQuery.data ?? [];

  return (
    <div className="space-y-6">
      <PreviewSection regimes={regimes} standings={standings} loadingRegimes={regimesQuery.isLoading} />

      <StandingsSection
        expiring={expiring}
        all={standings}
        loading={expiringQuery.isLoading || standingsQuery.isLoading}
        today={today}
      />

      <SchemesSection
        regimes={regimes}
        loading={regimesQuery.isLoading}
        onSeed={() => seed.mutate()}
        seeding={seed.isPending}
      />
    </div>
  );
}

/* ── Preview ───────────────────────────────────────────────────────────── */

function PreviewSection({
  regimes,
  standings,
  loadingRegimes,
}: {
  regimes: Regime[];
  standings: PartyStatus[];
  loadingRegimes: boolean;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [regimeId, setRegimeId] = useState('');
  const [grossAmount, setGrossAmount] = useState('');
  const [materials, setMaterials] = useState('');
  const [vat, setVat] = useState('');
  const [currency, setCurrency] = useState('');
  const [bandCode, setBandCode] = useState('');
  const [partyStatusId, setPartyStatusId] = useState('');
  const [asOf, setAsOf] = useState('');
  const [result, setResult] = useState<DeductionPreview | null>(null);

  const regime = regimes.find((r) => r.id === regimeId);
  // A standing is recorded against one scheme, so offering the others would
  // offer a band the picked scheme does not define.
  const eligibleStandings = standings.filter((s) => s.regime_id === regimeId);

  const preview = useMutation({
    mutationFn: () =>
      previewDeduction({
        regime_id: regimeId,
        gross_amount: toDecimalPayloadString(grossAmount),
        qualifying_materials: toDecimalPayloadString(materials),
        vat_amount: toDecimalPayloadString(vat),
        currency_code: currency.toUpperCase(),
        band_code: bandCode,
        party_status_id: partyStatusId || null,
        as_of: asOf || null,
      }),
    onSuccess: setResult,
    onError: (err: unknown) => {
      setResult(null);
      addToast({
        type: 'error',
        title: t('tax_withholding.preview_failed', { defaultValue: 'Could not work out the deduction' }),
        message: getErrorMessage(err),
      });
    },
  });

  // The scheme carries its own currency, so this is a prefill and the field
  // stays editable. These schemes exist because work crosses a border, and a
  // job billed in another currency is ordinary.
  const onRegimeChange = (id: string) => {
    setRegimeId(id);
    setBandCode('');
    setPartyStatusId('');
    setResult(null);
    const picked = regimes.find((r) => r.id === id);
    if (picked && !currency) setCurrency(picked.currency_code);
  };

  const ready = !!regimeId && grossAmount.trim() !== '' && currency.length === 3;

  if (loadingRegimes) {
    return <p className="text-sm text-content-secondary">{t('common.loading', { defaultValue: 'Loading...' })}</p>;
  }

  if (regimes.length === 0) {
    return (
      <EmptyState
        icon={<Landmark className="h-8 w-8" />}
        title={t('tax_withholding.no_schemes_title', { defaultValue: 'No withholding schemes on file' })}
        description={t('tax_withholding.no_schemes_body', {
          defaultValue:
            'A deduction is worked out from a scheme, so install the shipped ones below before pricing a payment. Nothing already on file is changed by that.',
        })}
      />
    );
  }

  return (
    <section aria-label={t('tax_withholding.preview_label', { defaultValue: 'Deduction preview' })}>
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Calculator className="h-4 w-4 text-oe-blue" />
        {t('tax_withholding.preview_title', { defaultValue: 'What does this payment actually pay out' })}
      </h3>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('tax_withholding.preview_note', {
          defaultValue:
            'Nothing is stored. Ask before the payment is agreed, and the answer names the band it landed on and why that is not another one.',
        })}
      </p>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <form
          className="grid gap-3 rounded-lg border border-border-light p-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (ready) preview.mutate();
          }}
        >
          <label className="flex flex-col gap-1 text-sm sm:col-span-2">
            {t('tax_withholding.field_scheme', { defaultValue: 'Withholding scheme' })}
            <select
              value={regimeId}
              onChange={(e) => onRegimeChange(e.target.value)}
              className="rounded border border-border-light bg-surface-primary p-2"
              required
            >
              <option value="">{t('tax_withholding.field_scheme_pick', { defaultValue: 'Pick a scheme' })}</option>
              {regimes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.country_code} - {r.scheme_name}
                </option>
              ))}
            </select>
          </label>

          <div className="grid grid-cols-[1fr_6rem] gap-2 sm:col-span-2">
            <label className="flex flex-col gap-1 text-sm">
              {t('tax_withholding.field_gross', { defaultValue: 'Gross amount' })}
              <input
                inputMode="decimal"
                value={grossAmount}
                onChange={(e) => setGrossAmount(e.target.value)}
                className="rounded border border-border-light bg-surface-primary p-2"
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              {t('tax_withholding.field_currency', { defaultValue: 'Currency' })}
              <input
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase().slice(0, 3))}
                maxLength={3}
                className="rounded border border-border-light bg-surface-primary p-2 uppercase"
                required
              />
            </label>
          </div>

          <label className="flex flex-col gap-1 text-sm">
            {t('tax_withholding.field_materials', { defaultValue: 'Qualifying materials' })}
            <input
              inputMode="decimal"
              value={materials}
              onChange={(e) => setMaterials(e.target.value)}
              className="rounded border border-border-light bg-surface-primary p-2"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            {t('tax_withholding.field_vat', { defaultValue: 'VAT' })}
            <input
              inputMode="decimal"
              value={vat}
              onChange={(e) => setVat(e.target.value)}
              className="rounded border border-border-light bg-surface-primary p-2"
            />
          </label>

          {/* Whether either figure moves the taxable base is the scheme's
              decision, not the form's. Saying so beside the inputs is cheaper
              than a user typing a materials figure, watching nothing change,
              and concluding the screen is broken. */}
          {regime && (
            <p className="text-xs text-content-tertiary sm:col-span-2">
              {t('tax_withholding.exclusions_note', {
                defaultValue: 'Under this scheme, materials are {{materials}} and VAT is {{vat}}.',
                materials: regime.materials_excluded
                  ? t('tax_withholding.excluded', { defaultValue: 'taken out of the taxable base' })
                  : t('tax_withholding.not_excluded', { defaultValue: 'left in the taxable base' }),
                vat: regime.vat_excluded
                  ? t('tax_withholding.excluded', { defaultValue: 'taken out of the taxable base' })
                  : t('tax_withholding.not_excluded', { defaultValue: 'left in the taxable base' }),
              })}
            </p>
          )}

          <label className="flex flex-col gap-1 text-sm">
            {t('tax_withholding.field_band', { defaultValue: 'Rate band' })}
            <select
              value={bandCode}
              onChange={(e) => setBandCode(e.target.value)}
              className="rounded border border-border-light bg-surface-primary p-2"
              disabled={!regime}
            >
              <option value="">
                {t('tax_withholding.field_band_auto', { defaultValue: 'Let the scheme decide' })}
              </option>
              {(regime?.bands ?? []).map((band) => (
                <option key={band.code} value={band.code}>
                  {band.label || band.code} - {band.rate_pct}%
                </option>
              ))}
            </select>
            {/* Null here means the scheme defines no such band, which is not
                the same answer as a band that deducts nothing: three of the
                shipped schemes have a real 0% band. */}
            {bandCode && (
              <span className="text-xs text-content-tertiary">
                {bandRate(regime, bandCode) === null
                  ? t('tax_withholding.band_undefined', {
                      defaultValue: 'This scheme defines no such band.',
                    })
                  : t('tax_withholding.band_rate_hint', {
                      defaultValue: 'Asks for {{rate}}%, subject to the verification behind it.',
                      rate: bandRate(regime, bandCode),
                    })}
              </span>
            )}
          </label>

          <label className="flex flex-col gap-1 text-sm">
            {t('tax_withholding.field_party', { defaultValue: 'Party standing' })}
            <select
              value={partyStatusId}
              onChange={(e) => setPartyStatusId(e.target.value)}
              className="rounded border border-border-light bg-surface-primary p-2"
              disabled={!regime}
            >
              <option value="">
                {t('tax_withholding.field_party_none', { defaultValue: 'No standing on record' })}
              </option>
              {eligibleStandings.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.party_name || s.party_id} - {s.band_code}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm sm:col-span-2">
            {t('tax_withholding.field_as_of', { defaultValue: 'Judge the standing as of' })}
            <input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="rounded border border-border-light bg-surface-primary p-2"
            />
            <span className="text-xs text-content-tertiary">
              {t('tax_withholding.field_as_of_note', {
                defaultValue:
                  'Left empty this is today. Set it to the date of a payment run priced ahead, so a verification that lapses before then is caught now.',
              })}
            </span>
          </label>

          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" size="sm" disabled={!ready || preview.isPending}>
              {t('tax_withholding.preview_submit', { defaultValue: 'Work out the deduction' })}
            </Button>
          </div>
        </form>

        <div>
          {result ? (
            <PreviewResult result={result} regime={regime} />
          ) : (
            <EmptyState
              icon={<Calculator className="h-8 w-8" />}
              title={t('tax_withholding.preview_empty_title', { defaultValue: 'No figure yet' })}
              description={t('tax_withholding.preview_empty_body', {
                defaultValue:
                  'Pick a scheme and a gross amount. The answer names the taxable base, what is withheld and what is left to pay.',
              })}
            />
          )}
        </div>
      </div>
    </section>
  );
}

function PreviewResult({ result, regime }: { result: DeductionPreview; regime: Regime | undefined }) {
  const { t } = useTranslation();
  const currency = result.currency_code;
  const bandLabel = findBand(regime, result.band_code)?.label || result.band_code;

  return (
    <div className="space-y-4 rounded-lg border border-border-light p-4">
      {/* The answer the module exists to give, so it leads. */}
      <div>
        <p className="text-xs uppercase tracking-wide text-content-tertiary">
          {t('tax_withholding.net_payable_label', { defaultValue: 'Net payable' })}
        </p>
        <p className="text-2xl font-semibold">{formatCurrency(result.net_payable, currency)}</p>
        {/* A flag, not a restatement. The server's own reason below names the
            actual limit and its currency, which is more than this can say. */}
        {result.below_threshold && (
          <Badge variant="warning" size="sm">
            {t('tax_withholding.below_threshold_badge', {
              defaultValue: 'Under the scheme exemption limit',
            })}
          </Badge>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <FigureRow
          label={t('tax_withholding.gross_label', { defaultValue: 'Gross amount' })}
          value={formatCurrency(result.gross_amount, currency)}
        />
        <FigureRow
          label={t('tax_withholding.taxable_base_label', { defaultValue: 'Taxable base' })}
          value={formatCurrency(result.taxable_base, currency)}
        />
        <FigureRow
          label={t('tax_withholding.tax_withheld_label', { defaultValue: 'Tax withheld' })}
          value={formatCurrency(result.tax_withheld, currency)}
        />
        <FigureRow
          label={t('tax_withholding.rate_label', { defaultValue: 'Rate applied' })}
          value={t('tax_withholding.rate_value', {
            defaultValue: '{{rate}}% on band {{band}}',
            rate: result.rate_pct,
            band: bandLabel,
          })}
        />
      </dl>

      {/* An expired verification silently dropping a party to the default band
          is the exact surprise this module exists to prevent, so it is stated
          rather than left to be inferred from a rate that looks high. */}
      {result.band_downgraded_from && (
        <div className="flex items-start gap-2 rounded border border-semantic-warning/40 bg-semantic-warning/5 p-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" />
          <div className="text-sm">
            <p className="font-medium">
              {t('tax_withholding.downgraded_title', {
                defaultValue: 'Band {{from}} could not be used; {{to}} applied instead',
                from: result.band_downgraded_from,
                to: result.band_code,
              })}
            </p>
            <p className="text-xs text-content-tertiary">
              {t('tax_withholding.downgraded_body', {
                defaultValue:
                  'The scheme default is its highest-rate band. This payment withholds more than the party expects unless the verification behind the lower band is put right first.',
              })}
            </p>
          </div>
        </div>
      )}

      {result.reasons.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold">
            {t('tax_withholding.reasons_title', { defaultValue: 'What the scheme said, in full' })}
          </h4>
          <p className="mb-1 text-xs text-content-tertiary">
            {t('tax_withholding.reasons_note', {
              defaultValue: 'The flags above are drawn from this, which is the whole account.',
            })}
          </p>
          {/* Prose the server wrote, rendered as it came. Unlike a validation
              finding these carry no i18n key, so there is nothing to look up. */}
          <ul className="list-disc space-y-1 pl-5 text-sm text-content-secondary">
            {result.reasons.map((reason, i) => (
              <li key={`${i}-${reason}`}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function FigureRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-content-secondary">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </>
  );
}

/* ── Party standings ───────────────────────────────────────────────────── */

function StandingsSection({
  expiring,
  all,
  loading,
  today,
}: {
  expiring: PartyStatus[];
  all: PartyStatus[];
  loading: boolean;
  today: string;
}) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);

  // The server's expiring list is a *forward* window from today, so a
  // verification that ran out three months ago is not in it. That is the worse
  // case of the two - deductions have already been taken at the wrong band -
  // and it would otherwise only be visible behind the "show every standing"
  // toggle. Nothing extra is fetched: these rows are already in memory.
  const lapsed = useMemo(
    () => all.filter((standing) => standingState(standing, today, EXPIRY_WINDOW_DAYS) === 'lapsed'),
    [all, today],
  );

  if (loading) {
    return <p className="text-sm text-content-secondary">{t('common.loading', { defaultValue: 'Loading...' })}</p>;
  }

  return (
    <section aria-label={t('tax_withholding.standings_label', { defaultValue: 'Party standings' })}>
      {lapsed.length > 0 && (
        <div className="mb-4">
          <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
            <ShieldAlert className="h-4 w-4 text-semantic-error" />
            {t('tax_withholding.lapsed_title', { defaultValue: 'Verifications that already ran out' })}
            <Badge variant="error" size="sm" dot>
              {t('tax_withholding.lapsed_count', {
                defaultValue: '{{count}} lapsed',
                count: lapsed.length,
              })}
            </Badge>
          </h3>
          <p className="mb-2 text-xs text-content-tertiary">
            {t('tax_withholding.lapsed_note', {
              defaultValue:
                'Every payment made to these parties since the date shown was deducted at the scheme default rate, whether or not anyone meant it. Renewing the verification fixes the next payment, not the ones already remitted.',
            })}
          </p>
          <StandingList standings={lapsed} today={today} />
        </div>
      )}

      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <BadgeCheck className="h-4 w-4 text-oe-blue" />
        {t('tax_withholding.standings_title', { defaultValue: 'Verifications running out' })}
        {expiring.length > 0 && (
          <Badge variant="warning" size="sm" dot>
            {t('tax_withholding.standings_count', {
              defaultValue: '{{count}} in the next {{days}} days',
              count: expiring.length,
              days: EXPIRY_WINDOW_DAYS,
            })}
          </Badge>
        )}
      </h3>
      <p className="mb-2 text-xs text-content-tertiary">
        {t('tax_withholding.standings_note', {
          defaultValue:
            'Read this before a payment run. Afterwards it is a record of deductions taken at the wrong band. Expiry is worked out per read and never stored, so this is as fresh as the page.',
        })}
      </p>

      {expiring.length === 0 ? (
        <EmptyState
          icon={<BadgeCheck className="h-8 w-8" />}
          title={t('tax_withholding.standings_clear_title', { defaultValue: 'Nothing lapsing soon' })}
          description={t('tax_withholding.standings_clear_body', {
            defaultValue:
              'No recorded verification runs out inside the window. A standing with no end date never appears here, which is not the same as one that was checked.',
          })}
        />
      ) : (
        <StandingList standings={expiring} today={today} />
      )}

      {all.length > 0 && (
        <div className="mt-3">
          <Button size="sm" variant="ghost" onClick={() => setShowAll((v) => !v)}>
            {showAll
              ? t('tax_withholding.hide_all_standings', { defaultValue: 'Hide every standing' })
              : // `total` rather than `count` on purpose: a number in brackets
                // does not change the sentence around it, and naming it `count`
                // would make i18next demand plural forms of this key in every
                // locale for no difference in what any of them read.
                t('tax_withholding.show_all_standings', {
                  defaultValue: 'Show every standing on file ({{total}})',
                  total: all.length,
                })}
          </Button>
          {showAll && (
            <div className="mt-2">
              <StandingList standings={all} today={today} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function StandingList({ standings, today }: { standings: PartyStatus[]; today: string }) {
  const { t } = useTranslation();

  return (
    <ul className="divide-y divide-border-light rounded-lg border border-border-light">
      {standings.map((standing) => {
        const state = standingState(standing, today, EXPIRY_WINDOW_DAYS);
        return (
          <li key={standing.id} className="flex flex-col gap-1 p-3">
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-medium">
                {standing.party_name ||
                  t('tax_withholding.unnamed_party', { defaultValue: 'Unnamed party' })}
              </span>
              <Badge variant={standingVariant(state)} size="sm">
                {t(STATE_LABEL[state].key, { defaultValue: STATE_LABEL[state].en })}
              </Badge>
              <Badge variant="neutral" size="sm">
                {standing.band_code}
              </Badge>
            </span>
            <span className="text-sm text-content-secondary">
              {t('tax_withholding.standing_window', {
                defaultValue: 'Valid {{from}} to {{to}}',
                from: standing.valid_from,
                to:
                  standing.valid_to ||
                  t('tax_withholding.no_end_date', { defaultValue: 'no end date' }),
              })}
            </span>
            <ExpiryPhrase standing={standing} />
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The countdown in words.
 *
 * `days_to_expiry` runs negative once the window has closed, so rendering it
 * straight prints "runs out in -12 days". Past and future are different
 * sentences, and a standing with no end date is neither.
 */
function ExpiryPhrase({ standing }: { standing: PartyStatus }) {
  const { t } = useTranslation();
  const days = standing.days_to_expiry;

  let phrase: string;
  if (days === null) {
    phrase = t('tax_withholding.expiry_open_ended', {
      defaultValue: 'No end date recorded, so nothing here will ever flag it.',
    });
  } else if (days < 0) {
    phrase = t('tax_withholding.expiry_past', {
      defaultValue: 'Lapsed {{count}} days ago.',
      count: Math.abs(days),
    });
  } else if (days === 0) {
    phrase = t('tax_withholding.expiry_today', { defaultValue: 'Runs out today.' });
  } else {
    phrase = t('tax_withholding.expiry_future', {
      defaultValue: 'Runs out in {{count}} days.',
      count: days,
    });
  }

  return <span className="text-xs text-content-tertiary">{phrase}</span>;
}

/* ── Schemes ───────────────────────────────────────────────────────────── */

function SchemesSection({
  regimes,
  loading,
  onSeed,
  seeding,
}: {
  regimes: Regime[];
  loading: boolean;
  onSeed: () => void;
  seeding: boolean;
}) {
  const { t } = useTranslation();

  return (
    <section aria-label={t('tax_withholding.schemes_label', { defaultValue: 'Withholding schemes' })}>
      <div className="mb-1 flex flex-wrap items-center gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Landmark className="h-4 w-4 text-oe-blue" />
          {t('tax_withholding.schemes_title', { defaultValue: 'Schemes and the rates they apply' })}
        </h3>
        <Button size="sm" variant="secondary" onClick={onSeed} disabled={seeding}>
          <Download className="mr-1 h-4 w-4" />
          {t('tax_withholding.seed', { defaultValue: 'Install the shipped schemes' })}
        </Button>
      </div>
      <p className="mb-2 text-xs text-content-tertiary">
        {t('tax_withholding.schemes_note', {
          defaultValue:
            'Installing only fills gaps. A scheme already on file keeps the rates it has, because an operator who edited one did so for a reason.',
        })}
      </p>

      {loading ? (
        <p className="text-sm text-content-secondary">{t('common.loading', { defaultValue: 'Loading...' })}</p>
      ) : regimes.length === 0 ? (
        <EmptyState
          icon={<Landmark className="h-8 w-8" />}
          title={t('tax_withholding.schemes_empty_title', { defaultValue: 'No schemes yet' })}
          description={t('tax_withholding.schemes_empty_body', {
            defaultValue:
              'The module ships with schemes for several jurisdictions. Install them, then edit the rates if a ruling in your business says otherwise.',
          })}
        />
      ) : (
        <ul className="space-y-3">
          {regimes.map((regime) => (
            <SchemeCard key={regime.id} regime={regime} />
          ))}
        </ul>
      )}
    </section>
  );
}

function SchemeCard({ regime }: { regime: Regime }) {
  const { t } = useTranslation();

  return (
    <li className="rounded-lg border border-border-light p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{regime.scheme_name}</span>
        <Badge variant="neutral" size="sm">
          {regime.country_code}
        </Badge>
        {!regime.is_active && (
          <Badge variant="warning" size="sm">
            {t('tax_withholding.scheme_retired', { defaultValue: 'Retired' })}
          </Badge>
        )}
      </div>
      {(regime.legal_reference || regime.authority) && (
        <p className="mt-0.5 text-xs text-content-tertiary">
          {[regime.legal_reference, regime.authority].filter(Boolean).join(' · ')}
        </p>
      )}

      <table className="mt-2 w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-content-tertiary">
            <th className="font-normal">{t('tax_withholding.band_col', { defaultValue: 'Band' })}</th>
            <th className="font-normal">{t('tax_withholding.rate_col', { defaultValue: 'Rate' })}</th>
            <th className="font-normal">
              {t('tax_withholding.verification_col', { defaultValue: 'Needs verification' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {regime.bands.map((band) => (
            <tr key={band.code}>
              <td className="py-0.5">
                {band.label || band.code}
                {band.code === regime.default_band_code && (
                  <span className="ml-2 text-xs text-content-tertiary">
                    {t('tax_withholding.default_band', { defaultValue: 'default' })}
                  </span>
                )}
              </td>
              {/* The rate is the string the server sent. Parsing it to render it
                  would be this screen taking responsibility for a figure filed
                  with a tax authority. */}
              <td className="py-0.5">{band.rate_pct}%</td>
              <td className="py-0.5 text-content-secondary">
                {band.requires_verification
                  ? t('common.yes', { defaultValue: 'Yes' })
                  : t('common.no', { defaultValue: 'No' })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="mt-2 text-xs text-content-tertiary">
        {t('tax_withholding.scheme_rules', {
          defaultValue:
            'Currency {{currency}}. Materials {{materials}}, VAT {{vat}}. Verification runs {{months}} months.',
          currency: regime.currency_code,
          materials: regime.materials_excluded
            ? t('tax_withholding.excluded_short', { defaultValue: 'excluded' })
            : t('tax_withholding.included_short', { defaultValue: 'included' }),
          vat: regime.vat_excluded
            ? t('tax_withholding.excluded_short', { defaultValue: 'excluded' })
            : t('tax_withholding.included_short', { defaultValue: 'included' }),
          months: regime.verification_validity_months,
        })}
        {regime.threshold_amount !== null && (
          <>
            {' '}
            {t('tax_withholding.scheme_threshold', {
              defaultValue: 'Exemption limit {{amount}}.',
              amount: formatCurrency(regime.threshold_amount, regime.currency_code),
            })}
          </>
        )}
      </p>
    </li>
  );
}
