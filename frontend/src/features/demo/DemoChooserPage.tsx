// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * First screen after signing in to the public demo: pick the kind of company
 * you want to see. Each card opens its showcase project with that company's
 * look and a menu cut to its work.
 */

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, Globe, SlidersHorizontal, Sparkles } from 'lucide-react';
import { ACCENT_SWATCH, FONT_STACK } from '@/shared/lib/appearance';
import { DEMO_PROFILES, type DemoProfile } from '@/shared/lib/demoProfiles';
import { fmtNumber } from '@/shared/lib/formatters';
import { navGroups } from '@/app/layout/navCatalog';
import { useDemoProjects } from '@/shared/ui/DemoSwitcherBar';
import { HexMark, type HexBuildingKind } from '@/shared/ui/HexMark';
import { companyThumbFor } from '@/features/cases/caseFaces';

/**
 * The picture in each card's hex: the site scene of the company type the demo
 * plays (the same thumbs the Cases hub uses), and a building drawing when none.
 */
const DEMO_FACE: Record<string, { companyType: string; kind: HexBuildingKind }> = {
  'full-showcase-riyadh': { companyType: 'full_enterprise', kind: 'hospital' },
  'residential-berlin': { companyType: 'general_contractor', kind: 'residential' },
  'office-london': { companyType: 'commercial-manager', kind: 'tower' },
  'medical-us': { companyType: 'construction-manager', kind: 'hospital' },
  'condo-toronto': { companyType: 'real_estate_developer', kind: 'tower' },
};

export function demoFaceFor(slug: string): { src: string | null; kind: HexBuildingKind } {
  const face = DEMO_FACE[slug];
  if (!face) return { src: null, kind: 'warehouse' };
  return { src: companyThumbFor(face.companyType), kind: face.kind };
}

/** The platform with every module on: shown first and larger than the company cuts. */
const FEATURED_SLUG = 'full-showcase-riyadh';

const FOOTER_LINK =
  'inline-flex items-center gap-2 rounded-full border border-border bg-surface-primary px-4 py-2 text-sm font-semibold text-content-primary hover:bg-surface-tertiary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2';

function DemoCard({ profile, featured = false }: { profile: DemoProfile; featured?: boolean }) {
  const { t } = useTranslation();
  const { bySlug, open } = useDemoProjects();
  const allSections = navGroups.length;
  const accent = ACCENT_SWATCH[profile.appearance.accent];
  const sections = profile.groups ? profile.groups.length : allSections;
  const list = [1, 2, 3].map((i) => t(`${profile.stem}.point_${i}`));
  const face = demoFaceFor(profile.slug);
  return (
    <button
      type="button"
      onClick={() => open(profile.slug)}
      data-testid={`demo-card-${profile.slug}`}
      data-featured={featured || undefined}
      className={`group relative flex min-w-0 flex-col rounded-2xl border bg-surface-primary text-start shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 motion-reduce:transition-none motion-reduce:hover:translate-y-0 ${
        featured ? 'border-2 shadow-md' : 'border-border-light'
      }`}
      style={{ outlineColor: accent, ...(featured ? { borderColor: accent } : {}) }}
    >
      <HexMark src={face.src} kind={face.kind} accent={accent} size={featured ? 80 : 64} className="-top-4 -start-4" />
      <div className="h-2 w-full rounded-t-2xl" style={{ backgroundColor: accent }} />
      <div className={`flex flex-1 flex-col p-6 ${featured ? 'lg:flex-row lg:gap-10' : ''}`}>
        <div className="flex min-w-0 flex-1 flex-col">
          {featured && (
            <span
              className="mb-2 ms-16 inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold text-white"
              style={{ backgroundColor: accent }}
            >
              <Sparkles size={14} />
              {t('demo_chooser.featured_badge', { defaultValue: 'Full platform: every module' })}
            </span>
          )}
          <p className="ps-12 text-xs font-semibold uppercase tracking-wide" style={{ color: accent }}>
            {t(`${profile.stem}.audience`)}
          </p>
          <h2
            className="mt-1 ps-12 text-xl font-semibold text-content-primary"
            style={{ fontFamily: FONT_STACK[profile.appearance.font] }}
          >
            {t(`${profile.stem}.title`)}
          </h2>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-content-tertiary">
            <Globe size={14} className="shrink-0" aria-hidden="true" />
            <span className="font-medium text-content-secondary" data-testid={`demo-country-${profile.slug}`}>
              {t(`${profile.stem}.country`)}
            </span>
            <span aria-hidden="true">·</span>
            <span className="min-w-0 truncate">{bySlug.get(profile.slug)?.name}</span>
          </p>
          <p className="mt-3 text-sm text-content-secondary">{t(`${profile.stem}.body`)}</p>
        </div>
        <div className={`flex flex-1 flex-col ${featured ? 'lg:justify-center' : ''}`}>
          <ul className="mt-4 space-y-1.5 text-sm text-content-primary lg:mt-0">
            {list.map((point) => (
              <li key={point} className="flex gap-2">
                <Check size={16} className="mt-0.5 shrink-0" style={{ color: accent }} />
                <span>{point}</span>
              </li>
            ))}
          </ul>
          <div className="mt-auto flex items-center justify-between gap-3 pt-6">
            <span className="text-xs text-content-tertiary">
              {t('demo_chooser.sections', {
                defaultValue: 'Menu: {{n}} of {{total}} sections',
                n: fmtNumber(sections, 0),
                total: fmtNumber(allSections, 0),
              })}
            </span>
            <span
              className="flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold text-white transition group-hover:gap-2.5"
              style={{ backgroundColor: accent }}
            >
              {t('demo_chooser.open', { defaultValue: 'Open this demo' })}
              <ArrowRight size={16} className="rtl:rotate-180" />
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

export function DemoChooserPage() {
  const { t } = useTranslation();
  const { bySlug, loaded } = useDemoProjects();
  const installed = DEMO_PROFILES.filter((p) => bySlug.has(p.slug));
  const featured = installed.find((p) => p.slug === FEATURED_SLUG);
  const others = installed.filter((p) => p.slug !== FEATURED_SLUG);

  return (
    <div className="space-y-5 px-0 sm:px-4 lg:px-8 animate-fade-in">
      <header className="text-center">
        <h1 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('demo_switcher.label', { defaultValue: 'Demo projects' })}
        </h1>
        <p className="mt-1 text-2xl font-semibold text-content-primary">
          {t('demo_chooser.title', { defaultValue: 'Which company do you want to see?' })}
        </p>
        <p className="mx-auto mt-2 max-w-4xl text-base text-content-secondary">
          {t('demo_chooser.subtitle', {
            defaultValue:
              'Each demo is a real-sized project run by a different kind of company, with a menu cut to its work. Switch any time from the bar at the top.',
          })}
        </p>
      </header>

      {loaded && installed.length === 0 && (
        <p className="text-center text-content-secondary">
          {t('demo_chooser.none', { defaultValue: 'No demo project is installed on this server yet.' })}
        </p>
      )}

      {featured && (
        <div className="pt-3">
          <DemoCard profile={featured} featured />
        </div>
      )}

      {others.length > 0 && (
        <>
          <h2 className="pt-2 text-center text-sm font-medium text-content-secondary">
            {t('demo_chooser.variants_heading', {
              defaultValue: 'Or start from a variant cut to one kind of company',
            })}
          </h2>
          <div className="grid grid-cols-1 gap-x-6 gap-y-8 pt-3 sm:grid-cols-2 lg:grid-cols-3">
            {others.map((profile) => (
              <DemoCard key={profile.slug} profile={profile} />
            ))}
          </div>
        </>
      )}

      <section
        data-testid="demo-chooser-footer"
        className="flex flex-col gap-4 rounded-2xl border border-border-light bg-surface-secondary p-6 md:flex-row md:items-center md:justify-between"
      >
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-content-primary">
            {t('demo_chooser.footer_title', { defaultValue: 'Any package, for any country and any company' })}
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-content-secondary">
            {t('demo_chooser.footer_body', {
              defaultValue:
                'These demos are assembled from the same platform. Country packs add local standards, contracts and data; settings let you turn modules on or off and set your own look.',
            })}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-3">
          <Link to="/packs" data-testid="demo-footer-packs" className={FOOTER_LINK}>
            <Globe size={16} />
            {t('demo_chooser.footer_packs', { defaultValue: 'Country packs' })}
          </Link>
          <Link to="/settings" data-testid="demo-footer-settings" className={FOOTER_LINK}>
            <SlidersHorizontal size={16} />
            {t('demo_chooser.footer_settings', { defaultValue: 'Modules and look in settings' })}
          </Link>
        </div>
      </section>
    </div>
  );
}

export default DemoChooserPage;
