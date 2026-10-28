// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "What this is / how it fits" intro for the Basis of Estimate page. Explains,
// in one glance, what the document is and how it connects to the rest of the
// platform: the coverage check reads the BOQ, the qualifications are drafted
// from it, the coverage flags link back to the bill / Validation, and the
// finished basis is exported or attached to the tender. Every connected module
// is a real link so the integration is obvious. Pure presentation, no fetching.

import { Fragment, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowRight, ClipboardCheck, FileText, Flag, Gauge, Send } from 'lucide-react';

/** A compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * Numbered flow + integration map for the Basis of Estimate. Mirrors the
 * `HowNormsWork` card in norm-expansion so the two clarity intros read the same
 * across the platform. Routes are confirmed to exist in App.tsx (/boq,
 * /validation, /tendering).
 */
export function HowBasisWorks() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <ClipboardCheck size={14} className="text-oe-blue" />,
      title: t('estimate_basis.flow_1_title', { defaultValue: 'BOQ coverage check' }),
      desc: t('estimate_basis.flow_1_desc', {
        defaultValue:
          'The bill of quantities is scanned for which trades are present, which expected trades are missing, and positions that are unpriced, provisional or missing a quantity.',
      }),
    },
    {
      icon: <FileText size={14} className="text-oe-blue" />,
      title: t('estimate_basis.flow_2_title', { defaultValue: 'Draft the qualifications' }),
      desc: t('estimate_basis.flow_2_desc', {
        defaultValue:
          'Inclusions, exclusions and assumptions are drafted automatically from that coverage. Edit, toggle or add your own lines.',
      }),
    },
    {
      // New step, new keys. The four that were here keep their own keys and
      // wording: changing a `defaultValue` on a key the locales already carry
      // changes nothing on screen, because the locale file wins.
      icon: <Gauge size={14} className="text-oe-blue" />,
      title: t('estimate_basis.flow_class_title', { defaultValue: 'State the accuracy class' }),
      desc: t('estimate_basis.flow_class_desc', {
        defaultValue:
          'The platform reads how much of the estimate was measured rather than typed and suggests an AACE class 1 to 5. You confirm or override it, and the estimate gains a published accuracy range.',
      }),
    },
    {
      icon: <Flag size={14} className="text-oe-blue" />,
      title: t('estimate_basis.flow_3_title', { defaultValue: 'Review the coverage flags' }),
      desc: t('estimate_basis.flow_3_desc', {
        defaultValue:
          'Each gap links straight to the bill or to Validation, so you can resolve it before the estimate goes out.',
      }),
    },
    {
      icon: <Send size={14} className="text-oe-blue" />,
      title: t('estimate_basis.flow_4_title', { defaultValue: 'Export or attach to tender' }),
      desc: t('estimate_basis.flow_4_desc', {
        defaultValue:
          'Download the basis as Markdown for a proposal, or attach it to the tender so bidders see the same scope.',
      }),
    },
  ];

  // The page wraps this in a `CollapsibleSection`, which supplies the heading
  // and the frame. A card and an `<h2>` here would duplicate both.
  return (
    <div>
      <p className="text-xs text-content-tertiary">
        {t('estimate_basis.flow_intro', {
          defaultValue:
            'Basis of Estimate drafts the inclusions, exclusions and assumptions behind your number - auto-derived from the BOQ trade coverage - so a reviewer or client sees exactly what the estimate does and does not cover, and you can attach it to the tender.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('estimate_basis.flow_pulls', { defaultValue: 'Pulls from:' })}
          </span>{' '}
          <ModLink to="/boq">{t('estimate_basis.mod_boq', { defaultValue: 'BOQ' })}</ModLink> ·{' '}
          <ModLink to="/validation">
            {t('estimate_basis.mod_validation', { defaultValue: 'Validation' })}
          </ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('estimate_basis.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          <ModLink to="/tendering">
            {t('estimate_basis.mod_tendering', { defaultValue: 'Tendering' })}
          </ModLink>
        </span>
      </div>
    </div>
  );
}
