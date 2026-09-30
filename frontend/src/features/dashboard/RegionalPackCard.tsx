// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RegionalPackCard — which regional pack is switched on, and what it did.
 *
 * A regional pack is the single largest piece of setup this product does on a
 * user's behalf: it loads a market's cost database, sets the currency, wires
 * the tax rules, turns on that market's validation standards and switches the
 * screens into that market's language. All of that used to be invisible after
 * the wizard closed. An estimator could work for weeks on top of SINAPI prices
 * and Brazilian ISS tax without a screen anywhere saying so, and an estimator
 * with NO pack had nothing telling them one existed.
 *
 * So the card answers three questions and nothing else: which pack is on, what
 * it set up, and - when none is on - what one would do and where to get it.
 *
 * The tiles deliberately name what an estimator recognises. Not "cwicr_regions"
 * and "validation_rule_sets" but price databases and standards checked, with
 * the number beside them where a number is honest. The pack's own module ids
 * never reach the screen.
 *
 * WHY TILES AND NOT ROWS. The card used to be a stack of label/value rows with
 * a subtitle above them, sized for its default third of the dashboard. Two
 * things turned that into a mostly empty box. The grid cell stretched the card
 * to the height of the market cases card beside it, several times its own
 * height, and below `lg` the card runs full width, where each row put its
 * label at one edge and its value at the other. The tiles flow into as many
 * columns as the width holds (`auto-fit`), so the card is one or two tile rows
 * tall at any width, and the dashboard grid no longer stretches it (see
 * WIDGET_NO_STRETCH in DashboardPage).
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Blocks,
  Check,
  Coins,
  Database,
  Globe2,
  Languages,
  Receipt,
  RotateCw,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react';

import { SUPPORTED_LANGUAGES, normalizePackLocale } from '@/app/i18n';
import { CountryFlag, Skeleton } from '@/shared/ui';
import { usePartnerPack } from '@/shared/hooks/usePartnerPack';
import { packCountryCode, packNameSlug } from '@/shared/lib/regionalPack';
import { ruleSetLabel } from '@/features/validation/ruleSetLabels';

/** Where a reader with no pack goes to pick one. Same destination the
 *  co-brand badge uses (see `@/shared/ui/PartnerLogoBadge`). */
const PACKS_ROUTE = '/modules?tab=partner-packs';

/** The rule set every pack switches on alongside its market's own standard.
 *  It is a generic quality check rather than a standard, so naming it on the
 *  standards tile would crowd out the one word the reader is looking for. */
const GENERIC_RULE_SET = 'boq_quality';

/** Card shell shared by every state, so loading, error, empty and active all
 *  occupy the same frame and the dashboard does not jump between them. */
const SHELL = 'rounded-xl border border-border-light bg-surface-primary p-4 shadow-xs';

/** Tiles flow into as many columns as the card is wide: two at the default
 *  third of the dashboard, a single row at full width. `minmax` keeps the
 *  track floor explicit so a long language cannot widen the card. */
const TILE_GRID = 'grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] gap-2';

/** One "what it set up" fact: an icon, a label an estimator uses, the value. */
function PackTile({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: ReactNode }) {
  return (
    <li
      className="flex min-w-0 items-center gap-2.5 rounded-lg bg-surface-secondary/60 px-2.5 py-2"
      data-testid="regional-pack-tile"
    >
      <Icon size={15} strokeWidth={1.75} className="shrink-0 text-oe-blue" aria-hidden="true" />
      <div className="min-w-0">
        <p className="truncate text-2xs text-content-tertiary" title={label}>
          {label}
        </p>
        <div className="truncate text-xs font-semibold tabular-nums text-content-primary">{value}</div>
      </div>
    </li>
  );
}

/** A tick standing for "switched on", read aloud with the tile's label. */
function OnMark({ label }: { label: string }) {
  return (
    <Check size={14} strokeWidth={2.5} className="text-semantic-success" aria-label={label} role="img" />
  );
}

export function RegionalPackCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading, isError, refetch } = usePartnerPack();

  // The card's own skeleton, in the card's own frame. Returning null here left
  // the cell blank until the answer came: the grid's WidgetSkeleton is a
  // Suspense fallback, so it covers the lazy chunk and nothing after it.
  if (isLoading) {
    return (
      <div className={SHELL} aria-busy="true" data-testid="regional-pack-loading">
        <div className="flex items-center gap-3">
          <Skeleton width={28} height={20} rounded="sm" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton height={8} className="w-24" />
            <Skeleton height={12} className="w-40" />
          </div>
        </div>
        <ul className={`mt-3 ${TILE_GRID}`}>
          {[0, 1, 2, 3].map((i) => (
            <li key={i}>
              <Skeleton height={44} />
            </li>
          ))}
        </ul>
      </div>
    );
  }

  // A failed request is not the same answer as "no pack". Falling through to
  // the empty state would tell a reader whose pack is on that none is, and
  // offer to install what they already have.
  if (isError) {
    return (
      <div className={SHELL} role="alert" data-testid="regional-pack-error">
        <div className="flex items-center gap-3">
          <AlertTriangle size={18} strokeWidth={1.75} className="shrink-0 text-semantic-warning" aria-hidden="true" />
          <p className="min-w-0 flex-1 text-xs text-content-secondary">
            {t('dashboard.regional_pack_error', { defaultValue: 'Could not load your regional pack' })}
          </p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md text-xs font-semibold text-oe-blue transition-colors hover:text-oe-blue-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            <RotateCw size={13} aria-hidden="true" />
            {t('common.retry', { defaultValue: 'Retry' })}
          </button>
        </div>
      </div>
    );
  }

  const manifest = data?.active ? data.manifest : undefined;

  // No pack. This is a real, common and DESIGNED state rather than an error:
  // the community wheel deliberately ships no pack for Germany, Canada or
  // Spain, three of the markets with the most case studies, and a fresh
  // install has none applied whatever the market. Rendering nothing here would
  // leave the reader who most needs to know that packs exist as the one reader
  // who is never told.
  if (!manifest) {
    return (
      <div className={SHELL} data-testid="regional-pack-none">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-secondary text-content-tertiary">
            <Globe2 size={18} strokeWidth={1.75} aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('dashboard.regional_pack_none', { defaultValue: 'No regional pack is active' })}
            </h3>
            <p className="mt-0.5 text-xs leading-relaxed text-content-tertiary">
              {t('dashboard.regional_pack_none_body', {
                defaultValue:
                  "A regional pack sets up one market's prices, tax rules and standards for you, so you do not have to enter them by hand.",
              })}
            </p>
          </div>
        </div>
        {/* The Packs tab, NOT the onboarding wizard. The wizard is guarded on
            the same `oe_onboarding_completed` flag the dashboard first-run
            redirect writes, and it bounces a completed user back to `/` with
            `replace`, so this button did nothing at all for every reader who
            can see a dashboard - the guard is total, not intermittent. Only
            Settings' "restart onboarding" may route there, because it removes
            the flag first, and this card must not: silently restarting a
            finished user's setup is worse than the dead button was. The Packs
            tab asks the same question the button does, one pack card per
            market with Activate and the apply dialog behind it, and no guard
            sits in front of it. */}
        <button
          type="button"
          onClick={() => navigate(PACKS_ROUTE)}
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-oe-blue/90"
        >
          {t('dashboard.regional_pack_choose', { defaultValue: 'Install a country pack' })}
          <ArrowRight size={13} className="rtl:rotate-180" aria-hidden="true" />
        </button>
      </div>
    );
  }

  const country = packCountryCode(manifest);
  // The pack's own name, translated. Written as an inline template literal
  // inside t() because that is the only shape check_i18n_computed_keys.py can
  // see - see the note in @/shared/lib/regionalPack.
  const name = t(`modules.pp_name_${packNameSlug(manifest.slug)}`, {
    defaultValue: manifest.partner_name,
  });

  // The language the pack speaks, in that language's own words, resolved the
  // same way the app resolves it. "pt-BR" has to read Português (Brasil), not
  // the code, and not Portugal's Português.
  const uiLanguage = normalizePackLocale(manifest.default_locale);
  const languageName =
    SUPPORTED_LANGUAGES.find((l) => l.code === uiLanguage)?.name ?? manifest.default_locale;

  // validation_rule_SETS, never `validation_rule_packs`: the neighbouring
  // field is the one the manifest calls "documentation", the engine never
  // executes it, and naming one switches nothing on. Counting them would have
  // told a Mexican estimator that five rules were checking their bills when
  // two rule sets were. The tile names the market's own standards instead
  // ("DIN 276", "NRM"), which is what the reader recognises, and falls back to
  // a tick when the pack only switches on the generic quality checks.
  const standards = manifest.validation_rule_sets
    .filter((rs) => rs !== GENERIC_RULE_SET)
    .map((rs) => ruleSetLabel(rs, t))
    .join(' · ');
  const validationLabel = t('dashboard.validation_rules', { defaultValue: 'Validation rules' });
  const taxLabel = t('dashboard.regional_pack_taxes', { defaultValue: 'Local tax rules' });

  return (
    <div className={SHELL} data-testid="regional-pack-active">
      <div className="flex items-center gap-3">
        {country && country !== 'xx' ? (
          <CountryFlag code={country} size={28} className="shrink-0 rounded-sm shadow-sm" />
        ) : (
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-secondary text-content-tertiary">
            <Globe2 size={16} strokeWidth={1.75} aria-hidden="true" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('dashboard.regional_pack_title', { defaultValue: 'Your regional pack' })}
          </p>
          <h3 className="truncate text-sm font-semibold text-content-primary" title={name}>
            {name}
          </h3>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-semantic-success/10 px-2 py-0.5 text-2xs font-semibold text-semantic-success">
          <span className="h-1.5 w-1.5 rounded-full bg-semantic-success" aria-hidden="true" />
          {t('common.active', { defaultValue: 'Active' })}
        </span>
      </div>

      {/* Every tile is skipped rather than shown empty. A pack that ships no
          tax template is not a pack whose tax rules are "none", it is a pack
          that is silent on tax, and a zero printed against a label reads as
          a promise broken rather than a promise not made. */}
      <ul className={`mt-3 ${TILE_GRID}`}>
        <PackTile
          icon={Languages}
          label={t('dashboard.regional_pack_language', { defaultValue: 'Language' })}
          value={languageName}
        />
        <PackTile
          icon={Coins}
          label={t('common.currency', { defaultValue: 'Currency' })}
          value={manifest.default_currency}
        />
        {manifest.cwicr_regions.length > 0 && (
          <PackTile
            icon={Database}
            label={t('dashboard.regional_pack_prices', { defaultValue: 'Local price databases' })}
            value={manifest.cwicr_regions.length}
          />
        )}
        {manifest.validation_rule_sets.length > 0 && (
          <PackTile
            icon={ShieldCheck}
            label={validationLabel}
            value={standards || <OnMark label={validationLabel} />}
          />
        )}
        {manifest.default_tax_template && (
          <PackTile icon={Receipt} label={taxLabel} value={<OnMark label={taxLabel} />} />
        )}
        {manifest.default_modules.length > 0 && (
          <PackTile
            icon={Blocks}
            label={t('dashboard.regional_pack_modules', { defaultValue: 'Modules switched on' })}
            value={manifest.default_modules.length}
          />
        )}
      </ul>

      {/* The way to a different market. Quiet rather than a second primary
          button, because for a reader who is already set up this is a way
          out, not the next step. */}
      <button
        type="button"
        onClick={() => navigate(PACKS_ROUTE)}
        className="mt-3 inline-flex items-center gap-1.5 rounded-md text-xs font-semibold text-oe-blue transition-colors hover:text-oe-blue-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
      >
        {t('dashboard.regional_pack_manage', {
          defaultValue: 'Change or add a country pack',
        })}
        <ArrowRight size={13} className="rtl:rotate-180" aria-hidden="true" />
      </button>
    </div>
  );
}
