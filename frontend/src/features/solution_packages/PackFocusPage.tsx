// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ``/packs/focus``: what a pack install left on the menu, the first steps to
 * take with it, and the modules it hid, each one click away. "Show all
 * modules" reverses the focus. Hidden modules keep their data.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, CheckCircle2, EyeOff, Layers3, Loader2, Rocket } from 'lucide-react';
import { Breadcrumb, Button } from '@/shared/ui';
import { packNameSlug } from '@/shared/lib/regionalPack';
import { fmtList } from '@/shared/lib/formatters';
import { moduleDisplayNameKey } from '@/features/modules/moduleDisplayName';
import { ROUTE_BACKEND_MODULE } from '@/app/layout/Sidebar';
import { projectsApi } from '@/features/projects/api';
import { ruleSetLabel } from '@/features/validation/ruleSetLabels';
import {
  PACKAGES_QUERY_KEY,
  setModuleEnabled,
  showAllModules,
  useFocusPreview,
  useSolutionPackages,
  type FocusPreview,
} from './api';
import { buildFirstSteps, findDemoProjectId, type FirstStep } from './focus';
import { FocusModuleList } from './FocusModuleList';

export function usePackDisplayName() {
  const { t } = useTranslation();
  return (p: Pick<FocusPreview, 'slug' | 'name' | 'name_key'>) =>
    p.name_key
      ? t(p.name_key, { defaultValue: p.name })
      : t(`modules.pp_name_${packNameSlug(p.slug)}`, { defaultValue: p.name });
}

/** A standard or rule set id as people write it: `din276` reads "DIN 276", an unknown id gets a capital. */
function standardLabel(id: string, t: ReturnType<typeof useTranslation>['t']): string {
  const label = ruleSetLabel(id, t);
  return label === id.replace(/_/g, ' ') ? label.charAt(0).toUpperCase() + label.slice(1) : label;
}

function stepLabel(t: ReturnType<typeof useTranslation>['t'], step: FirstStep): string {
  switch (step.id) {
    case 'demo':
      return t('packs.step_demo', { defaultValue: 'Open the demo project: it is filled in, so every screen has data' });
    case 'boq':
      return step.param
        ? t('packs.step_boq_standard', { defaultValue: 'See the bill of quantities structured by {{standard}}', standard: standardLabel(step.param, t) })
        : t('packs.step_boq', { defaultValue: 'See the bill of quantities with prices' });
    case 'validation':
      return step.param
        ? t('packs.step_validation_rules', { defaultValue: 'Run validation with the pack rules ({{rules}})', rules: fmtList(step.param.split(/,\s*/).map((r) => standardLabel(r, t))) })
        : t('packs.step_validation', { defaultValue: 'Run validation and fix what it finds' });
    case 'export_gaeb':
      return t('packs.step_export_gaeb', { defaultValue: 'Export the bill as GAEB XML for the tender' });
    case 'reports':
      return t('packs.step_reports', { defaultValue: 'Export a report in the national format' });
    case 'costs':
      return t('packs.step_costs', { defaultValue: 'Browse the national cost database' });
    default:
      return t('packs.step_open_module', {
        defaultValue: 'Open {{module}}',
        module: t(moduleDisplayNameKey(step.param ?? ''), { defaultValue: (step.param ?? '').replace(/[_-]/g, ' ') }),
      });
  }
}

export function PackFocusSummary({ preview, modules }: { preview: FocusPreview; modules: Record<string, boolean> }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const packName = usePackDisplayName()(preview);
  const [resetting, setResetting] = useState(false);

  const on = Object.keys(modules).filter((k) => modules[k]).sort();
  const hidden = Object.keys(modules).filter((k) => modules[k] === false).sort();
  const hasDemo = preview.demo_template_ids.length > 0;
  const projects = useQuery({ queryKey: ['projects'], queryFn: projectsApi.list, enabled: hasDemo });
  const demoProjectId = hasDemo ? findDemoProjectId(projects.data ?? [], preview.demo_template_ids) : null;
  const steps = buildFirstSteps(preview, ROUTE_BACKEND_MODULE, demoProjectId);

  async function show(module: string) {
    await setModuleEnabled(module, true);
    await qc.invalidateQueries({ queryKey: PACKAGES_QUERY_KEY });
  }

  async function showAll() {
    setResetting(true);
    try {
      await showAllModules();
      await qc.invalidateQueries({ queryKey: PACKAGES_QUERY_KEY });
      navigate('/packs');
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="space-y-5" data-testid="pack-focus-summary">
      <section className="rounded-2xl border border-border-light bg-surface-elevated p-5 shadow-sm sm:p-6">
        <p className="inline-flex items-center gap-1.5 text-sm font-medium text-semantic-success">
          <CheckCircle2 size={16} aria-hidden />
          {t('packs.focus_installed', { defaultValue: '{{pack}} is set up', pack: packName })}
        </p>
        <h1 className="sr-only">{t('nav.packs', { defaultValue: 'Packs' })}</h1>
        <h2 className="mt-2 text-xl font-bold text-content-primary" data-testid="pack-focus-headline">
          {t('packs.focus_headline', {
            defaultValue: '{{on}} modules are on for {{pack}}. {{hidden}} others are hidden.',
            on: on.length,
            hidden: hidden.length,
            pack: packName,
          })}
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-content-secondary">
          {t('packs.focus_explain', {
            defaultValue: 'Hidden modules are not removed and keep their data. Add any of them back below with one click, or show everything again.',
          })}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <a href="#more-modules" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-oe-blue px-3 text-sm font-medium text-content-inverse hover:bg-oe-blue-hover">
            <Layers3 size={15} aria-hidden />
            {t('packs.focus_more', { defaultValue: 'Show more modules' })}
          </a>
          <Button variant="secondary" onClick={() => void showAll()} disabled={resetting} data-testid="pack-focus-show-all">
            {resetting && <Loader2 size={14} className="me-1.5 animate-spin" />}
            {t('packs.focus_show_all', { defaultValue: 'Show all modules' })}
          </Button>
        </div>
      </section>

      {steps.length > 0 && (
        <section className="rounded-2xl border border-border-light bg-surface-elevated p-5 shadow-sm">
          <h2 className="mb-3 inline-flex items-center gap-2 text-base font-semibold text-content-primary">
            <Rocket size={16} aria-hidden className="text-oe-blue" />
            {t('packs.focus_start', { defaultValue: 'Start here' })}
          </h2>
          <ol className="space-y-2" data-testid="pack-focus-steps">
            {steps.map((step, i) => (
              <li key={`${step.id}-${step.to}`}>
                <Link
                  to={step.to}
                  className="flex items-center gap-3 rounded-lg border border-border-light px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary"
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-xs font-semibold text-oe-blue">
                    {i + 1}
                  </span>
                  <span className="flex-1">{stepLabel(t, step)}</span>
                  <ArrowRight size={14} aria-hidden className="text-content-tertiary rtl:rotate-180" />
                </Link>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="rounded-2xl border border-border-light bg-surface-elevated p-5 shadow-sm">
        <h2 className="mb-3 text-base font-semibold text-content-primary">
          {t('packs.focus_on_title', { defaultValue: 'On in your menu' })}
        </h2>
        <FocusModuleList modules={on} testId="pack-focus-on" />
      </section>

      <section id="more-modules" className="scroll-mt-20 rounded-2xl border border-border-light bg-surface-elevated p-5 shadow-sm">
        <h2 className="mb-1 inline-flex items-center gap-2 text-base font-semibold text-content-primary">
          <EyeOff size={16} aria-hidden className="text-content-tertiary" />
          {t('packs.focus_hidden_title', { defaultValue: 'Hidden modules' })}
        </h2>
        <p className="mb-3 text-xs text-content-tertiary">
          {t('packs.focus_hidden_hint', { defaultValue: 'Click Show to put a module back in the menu.' })}
        </p>
        {hidden.length ? (
          <FocusModuleList modules={hidden} onShow={show} testId="pack-focus-hidden" />
        ) : (
          <p className="text-sm text-content-secondary">
            {t('packs.focus_none_hidden', { defaultValue: 'Every module is in your menu.' })}
          </p>
        )}
      </section>
    </div>
  );
}

export function PackFocusPage() {
  const { t } = useTranslation();
  const { data, isLoading } = useSolutionPackages();
  const slug = data?.state.focus_pack ?? null;
  const preview = useFocusPreview(slug);

  const crumbs = (
    <Breadcrumb
      items={[
        { label: t('nav.packs', { defaultValue: 'Packs' }), to: '/packs' },
        { label: t('packs.focus_crumb', { defaultValue: 'Your modules' }) },
      ]}
    />
  );

  if (isLoading || (slug && preview.isLoading)) {
    return <Loader2 className="animate-spin text-oe-blue" aria-label={t('common.loading', { defaultValue: 'Loading' })} />;
  }
  if (!slug || !preview.data || !data) {
    return (
      <div className="space-y-4">
        {crumbs}
        <div className="rounded-2xl border border-border-light bg-surface-elevated p-6 text-center" data-testid="pack-focus-empty">
          <p className="text-sm text-content-secondary">
            {t('packs.focus_none', { defaultValue: 'Your menu shows every module. Install a pack to keep only what it needs.' })}
          </p>
          <Link to="/packs" className="mt-3 inline-flex text-sm font-medium text-oe-blue hover:underline">
            {t('packs.all_packs', { defaultValue: 'All packs' })}
          </Link>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-4 animate-fade-in">
      {crumbs}
      <PackFocusSummary preview={preview.data} modules={data.state.modules} />
    </div>
  );
}

export default PackFocusPage;
