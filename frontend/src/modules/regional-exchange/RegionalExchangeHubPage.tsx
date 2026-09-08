// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RegionalExchangeHubPage - the way in to the twenty country exchange routes.
 *
 * Wave 5 Epic I collapsed twenty country modules into one polymorphic page and
 * kept each old slug (`/uk-nrm-exchange`, `/ru-gesn-exchange`, …) mounted for
 * bookmarks. Issue #217 ruled out twenty sidebar rows, and the BOQ link that
 * was to replace them was never written, so every one of the twenty was
 * reachable only by typing its URL. This page is that missing entry point: it
 * picks the country, then hands over to the route that already exists.
 *
 * It is a picker rather than a resolver on purpose. `regionalRegistry` resolves
 * a template by `id` and by route slug and by nothing else - there is no
 * region-to-template mapping to guess a country from a locale or a project, and
 * guessing wrong would silently apply the wrong trade-section breakdown to an
 * import. Twenty labelled cards ask the question instead of answering it badly.
 *
 * The card labels stay untranslated, matching the manifest's route titles: a
 * country label is the name of a measurement standard carrying its country
 * ("United Kingdom NRM 1/2", "Russia ГЭСН / ФЕР / ТЕР") and the standard half
 * has no translation in any language.
 *
 * Every string the page says in its own voice is an i18n key that all 43 full
 * locales already answer, `boq.preset_regional` for the heading and the
 * `regional.intro_*` trio for the information card. That is not the usual
 * freedom to name a key and add it: `scripts/check_i18n_orphan_keys.py` reads
 * only `app/locales/*.ts`, so a key answered by this module's own
 * `translations` bundle and by nothing else - `nav.regional_exchange` is one -
 * counts as answered by no locale the moment a `t()` call names it literally,
 * and the page would ship English in 42 languages. Reusing a translated key is
 * the honest way in until a locale pass can give the hub keys of its own.
 */

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { DismissibleInfo, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { COUNTRY_TEMPLATES } from './regionalRegistry';

export default function RegionalExchangeHubPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      {/* srTitle only - the same key the manifest gives this route as its
          `title`, so the top bar and this heading say one thing, which is the
          invariant `app/layout/Header.titleKeys.test.ts` exists to hold. */}
      <PageHeader srTitle={t('boq.preset_regional', { defaultValue: 'Regional standards' })} />

      <DismissibleInfo
        storageKey="regional-exchange-hub"
        title={t('regional.intro_title', {
          defaultValue: "Speak your country's tender format",
        })}
        more={
          t('regional.intro_more', { defaultValue: '' }) ? (
            <IntroRichText text={t('regional.intro_more')} />
          ) : undefined
        }
      >
        {t('regional.intro_body', {
          defaultValue:
            "Import and export BOQ data in your region's native structure (NRM in the UK, MasterFormat in the US, DPGF in France and others), with the right trade-section breakdown applied. The data lands in or comes from a normal BOQ, so the same estimate moves across markets without re-keying.",
        })}
      </DismissibleInfo>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {COUNTRY_TEMPLATES.map((tpl) => (
          <Link
            key={tpl.id}
            to={`/${tpl.routeSlug}`}
            data-testid={`regional-hub-card-${tpl.id}`}
            className="group flex items-start gap-3 rounded-xl border border-border-light bg-surface-primary p-4 text-left shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              {tpl.flag}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-semibold text-content-primary">
                {tpl.label}
              </span>
              <span className="mt-0.5 block text-2xs text-content-tertiary line-clamp-2">
                {tpl.formatHint}
              </span>
            </span>
            <ArrowRight
              size={14}
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-content-quaternary transition-transform duration-normal ease-oe group-hover:translate-x-0.5 rtl:rotate-180"
            />
          </Link>
        ))}
      </div>
    </div>
  );
}
