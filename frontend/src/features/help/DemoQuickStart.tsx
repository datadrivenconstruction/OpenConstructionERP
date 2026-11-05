// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DemoQuickStart - the top of "How it works" on the public demo: one headline,
// three quick-start buttons and a grid of short cards. Counts come from the
// loaded demo projects, the demo profiles and the module guide, never typed in.

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Database,
  ExternalLink,
  Info,
  Lock,
  Rocket,
  Server,
  Users,
  type LucideIcon,
} from 'lucide-react';

import { HexMark } from '@/shared/ui/HexMark';
import { useDemoProjects } from '@/shared/ui/DemoSwitcherBar';
import { DEMO_PROFILES } from '@/shared/lib/demoProfiles';
import { fmtList, fmtNumber } from '@/shared/lib/formatters';
import { MODULE_EXPLANATIONS } from './moduleExplanations';

const PRICING_URL = 'https://openconstructionerp.com/pricing';

interface Card {
  id: string;
  icon: LucideIcon;
  title: string;
  body: string;
  action: string;
  to: string;
  external?: boolean;
}

export function DemoQuickStart() {
  const { t } = useTranslation();
  const { demoMode, loaded, bySlug } = useDemoProjects();
  if (!demoMode) return null;

  const roles = fmtList(DEMO_PROFILES.map((p) => t(`${p.stem}.audience`)));
  const dataBody = [
    loaded
      ? t('howto.demo.data_projects', {
          defaultValue: 'Demo projects loaded right now: {{count}}.',
          count: bySlug.size,
        })
      : null,
    t('howto.demo.data_body', {
      defaultValue: '{{profiles}} company profiles and {{modules}} modules with a plain-language guide.',
      profiles: fmtNumber(DEMO_PROFILES.length),
      modules: fmtNumber(MODULE_EXPLANATIONS.length),
    }),
  ]
    .filter(Boolean)
    .join(' ');

  const choose = t('howto.demo.action_choose', { defaultValue: 'Choose a demo' });
  const openBoq = t('howto.demo.action_boq', { defaultValue: 'Open BOQs' });
  const validate = t('howto.demo.action_validation', { defaultValue: 'Run validation' });

  const cards: Card[] = [
    {
      id: 'what',
      icon: Info,
      title: t('howto.demo.what_title', { defaultValue: 'What this demo is' }),
      body: t('howto.demo.what_body', {
        defaultValue:
          'A live copy of OpenConstructionERP with sample companies and projects. Click anything: nothing you do here can break it.',
      }),
      action: choose,
      to: '/onboarding/demo',
    },
    {
      id: 'data',
      icon: Database,
      title: t('howto.demo.data_title', { defaultValue: 'What data is inside' }),
      body: dataBody,
      action: t('howto.demo.action_projects', { defaultValue: 'See projects' }),
      to: '/projects',
    },
    {
      id: 'try',
      icon: Rocket,
      title: t('howto.demo.try_title', { defaultValue: 'What to try first' }),
      body: t('howto.demo.try_body', {
        defaultValue:
          'Open a BOQ, match its positions to cost items, look at the schedule, run validation and export to GAEB or Excel.',
      }),
      action: t('howto.demo.action_costs', { defaultValue: 'Match costs' }),
      to: '/costs',
    },
    {
      id: 'roles',
      icon: Users,
      title: t('howto.demo.roles_title', { defaultValue: 'Roles you can switch to' }),
      body: t('howto.demo.roles_body', {
        defaultValue: 'Each demo plays one company and shows its own menu: {{roles}}.',
        roles,
      }),
      action: t('howto.demo.action_switch', { defaultValue: 'Switch company' }),
      to: '/onboarding/demo',
    },
    {
      id: 'limits',
      icon: Lock,
      title: t('howto.demo.limits_title', { defaultValue: 'Demo limits' }),
      body: t('howto.demo.limits_body', {
        defaultValue:
          'Saving and uploads are turned off, so every visitor sees the same data. Import your own GAEB or Excel files in your own install.',
      }),
      action: validate,
      to: '/validation',
    },
    {
      id: 'install',
      icon: Server,
      title: t('howto.demo.install_title', { defaultValue: 'Get your own install' }),
      body: t('howto.demo.install_body', {
        defaultValue: 'Self-host it free under AGPL-3.0, or take a commercial licence with support.',
      }),
      action: t('howto.demo.action_pricing', { defaultValue: 'See pricing' }),
      to: PRICING_URL,
      external: true,
    },
  ];

  const quick = [
    { label: choose, to: '/onboarding/demo', primary: true },
    { label: openBoq, to: '/boq', primary: false },
    { label: validate, to: '/validation', primary: false },
  ];

  return (
    <section className="mb-10" data-testid="demo-quick-start">
      <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <h2 className="text-xl font-bold text-content-primary">
          {t('howto.demo.headline', {
            defaultValue: 'Explore a working construction ERP on real demo projects',
          })}
        </h2>
        <div className="flex flex-wrap gap-2">
          {quick.map((q) => (
            <Link
              key={q.to}
              to={q.to}
              className={
                q.primary
                  ? 'inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-oe-blue/90'
                  : 'inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3.5 py-2 text-sm font-semibold text-content-primary transition hover:border-oe-blue/50'
              }
            >
              {q.label}
              <ArrowRight size={14} className="rtl:rotate-180" aria-hidden="true" />
            </Link>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-x-6 gap-y-8 pt-3 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((c) => {
          const link = (
            <>
              {c.action}
              {c.external ? (
                <ExternalLink size={13} aria-hidden="true" />
              ) : (
                <ArrowRight size={13} className="rtl:rotate-180" aria-hidden="true" />
              )}
            </>
          );
          const linkClass =
            'mt-auto inline-flex items-center gap-1 pt-3 text-sm font-semibold text-oe-blue hover:underline';
          return (
            <article
              key={c.id}
              data-testid={`demo-quick-card-${c.id}`}
              className="group relative flex min-w-0 flex-col rounded-2xl border border-border-light bg-surface-primary p-5 ps-14 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md motion-reduce:transition-none motion-reduce:hover:translate-y-0"
            >
              <HexMark icon={c.icon} size={48} className="-top-3 -start-3" />
              <h3 className="text-base font-bold text-content-primary">{c.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-content-secondary">{c.body}</p>
              {c.external ? (
                <a href={c.to} target="_blank" rel="noopener noreferrer" className={linkClass}>
                  {link}
                </a>
              ) : (
                <Link to={c.to} className={linkClass}>
                  {link}
                </Link>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
