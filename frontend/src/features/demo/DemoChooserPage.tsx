// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * First screen after signing in to the public demo: pick the kind of company
 * you want to see. Each card opens its showcase project with that company's
 * look and a menu cut to its work.
 */

import { useTranslation } from 'react-i18next';
import { ArrowRight, Check } from 'lucide-react';
import { ACCENT_SWATCH, FONT_STACK } from '@/shared/lib/appearance';
import { DEMO_PROFILES } from '@/shared/lib/demoProfiles';
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
  'consultancy-riyadh': { companyType: 'architecture_engineering', kind: 'tower' },
  'contractor-jeddah': { companyType: 'general_contractor', kind: 'tower' },
  'site-development-dammam': { companyType: 'civil_infrastructure', kind: 'bridge' },
  'full-showcase-riyadh': { companyType: 'full_enterprise', kind: 'hospital' },
  'residential-riyadh-offplan': { companyType: 'real_estate_developer', kind: 'residential' },
};

export function demoFaceFor(slug: string): { src: string | null; kind: HexBuildingKind } {
  const face = DEMO_FACE[slug];
  if (!face) return { src: null, kind: 'warehouse' };
  return { src: companyThumbFor(face.companyType), kind: face.kind };
}

export function DemoChooserPage() {
  const { t } = useTranslation();
  const { bySlug, loaded, open } = useDemoProjects();
  const allSections = navGroups.length;
  const cards = DEMO_PROFILES.filter((p) => bySlug.has(p.slug));

  return (
    <div className="space-y-5 animate-fade-in">
      <header className="text-center">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-content-tertiary">
          {t('demo_switcher.label', { defaultValue: 'Demo projects' })}
        </h1>
        <p className="mt-2 text-3xl font-bold text-content-primary">
          {t('demo_chooser.title', { defaultValue: 'Which company do you want to see?' })}
        </p>
        <p className="mx-auto mt-3 max-w-2xl text-base text-content-secondary">
          {t('demo_chooser.subtitle', {
            defaultValue:
              'Each demo is a real-sized project run by a different kind of company. The menu shows only the sections that company works in, so you see your own day, not every module. You can switch at any time from the bar at the top.',
          })}
        </p>
      </header>

      {loaded && cards.length === 0 && (
        <p className="text-center text-content-secondary">
          {t('demo_chooser.none', { defaultValue: 'No demo project is installed on this server yet.' })}
        </p>
      )}

      <div className="grid grid-cols-1 gap-x-6 gap-y-8 pt-3 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((profile) => {
          const accent = ACCENT_SWATCH[profile.appearance.accent];
          const sections = profile.groups ? profile.groups.length : allSections;
          const list = [1, 2, 3].map((i) => t(`${profile.stem}.point_${i}`));
          const face = demoFaceFor(profile.slug);
          return (
            <button
              key={profile.slug}
              type="button"
              onClick={() => open(profile.slug)}
              data-testid={`demo-card-${profile.slug}`}
              className="group relative flex min-w-0 flex-col rounded-2xl border border-border-light bg-surface-primary text-start shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 motion-reduce:transition-none motion-reduce:hover:translate-y-0"
              style={{ outlineColor: accent }}
            >
              <HexMark src={face.src} kind={face.kind} accent={accent} size={64} className="-top-4 -start-4" />
              <div className="h-2 w-full rounded-t-2xl" style={{ backgroundColor: accent }} />
              <div className="flex flex-1 flex-col p-6">
                <p className="ps-12 text-xs font-semibold uppercase tracking-wide" style={{ color: accent }}>
                  {t(`${profile.stem}.audience`)}
                </p>
                <h2
                  className="mt-1 ps-12 text-xl font-bold text-content-primary"
                  style={{ fontFamily: FONT_STACK[profile.appearance.font] }}
                >
                  {t(`${profile.stem}.title`)}
                </h2>
                <p className="mt-1 text-sm text-content-tertiary">{bySlug.get(profile.slug)?.name}</p>
                <p className="mt-3 text-sm text-content-secondary">{t(`${profile.stem}.body`)}</p>
                {list.length > 0 && (
                  <ul className="mt-4 space-y-1.5 text-sm text-content-primary">
                    {list.map((point) => (
                      <li key={point} className="flex gap-2">
                        <Check size={16} className="mt-0.5 shrink-0" style={{ color: accent }} />
                        <span>{point}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-auto flex items-center justify-between pt-6">
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
                    <ArrowRight size={16} />
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default DemoChooserPage;
