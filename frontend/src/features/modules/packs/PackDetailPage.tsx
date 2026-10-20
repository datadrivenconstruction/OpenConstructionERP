// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ``/packs/:slug``: one pack, what it carries, and what activating it changes.
 *
 * The "what changes" half is the backend's own dry run
 * (``GET /partner-pack/apply-preview/{slug}``), the same plan the apply dialog
 * confirms, so this page cannot promise anything the dialog would not do.
 * ``?setup=1`` opens that dialog on arrival; older links of the shape
 * ``/modules?tab=packs&pack=<slug>`` land here with it.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertTriangle,
  ArrowLeft,
  Boxes,
  Check,
  Database,
  ExternalLink,
  FolderKanban,
  Info,
  Languages,
  Mail,
  PackageX,
  Power,
  RefreshCw,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react';
import { Breadcrumb, Button } from '@/shared/ui';
import { PackEmblem } from '@/shared/ui/PackEmblem';
import { CountryFlag } from '@/shared/ui/CountryFlag';
import { packNameSlug } from '@/shared/lib/regionalPack';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { PartnerPackApplyDialog } from '../PartnerPackApplyDialog';
import { PartnerPackDeactivateDialog } from '../PartnerPackDeactivateDialog';
import { canInstallPacks, useApplyPreview } from '../partnerPacks';
import { presetModuleName } from '../companyProfiles';
import { asStringArray } from './packCatalog';
import { usePackCatalogData } from './PacksCatalog';
import { ViewerPackNotice } from './InstallPackPanel';
import { PACK_TYPE_META, useBandLabels } from './packLabels';

/** How many module names a list shows before it folds the rest into "+N". */
const MODULES_SHOWN = 12;

function Section({
  icon: Icon,
  title,
  children,
  testId,
}: {
  icon: LucideIcon;
  title: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <section className="rounded-xl border border-border-light bg-surface-elevated p-4 sm:p-5" data-testid={testId}>
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-content-primary">
        <Icon size={16} aria-hidden className="text-content-tertiary" />
        {title}
      </h3>
      {children}
    </section>
  );
}

function Chips({ items, tone = 'neutral' }: { items: string[]; tone?: 'neutral' | 'on' | 'off' }) {
  const { t } = useTranslation();
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, MODULES_SHOWN);
  return (
    <div className="flex flex-wrap gap-1.5">
      {shown.map((item) => (
        <span
          key={item}
          className={clsx(
            'inline-flex h-6 items-center rounded-md px-2 text-xs',
            tone === 'on' && 'bg-semantic-success-bg text-semantic-success',
            tone === 'off' && 'bg-semantic-error-bg text-semantic-error',
            tone === 'neutral' && 'bg-surface-secondary text-content-secondary',
          )}
        >
          {item}
        </span>
      ))}
      {items.length > MODULES_SHOWN && (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="inline-flex h-6 items-center rounded-md px-2 text-xs font-medium text-oe-blue hover:bg-oe-blue/5"
        >
          {all
            ? t('packs.show_less', { defaultValue: 'Show less' })
            : t('packs.show_more_n', { defaultValue: 'Show all: {{n}}', n: items.length })}
        </button>
      )}
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2 text-sm">
      <dt className="shrink-0 text-content-tertiary">{label}</dt>
      <dd className="min-w-0 text-end font-medium text-content-primary">{children}</dd>
    </div>
  );
}

export function PackDetailPage() {
  const { t, i18n } = useTranslation();
  const { slug = '' } = useParams<{ slug: string }>();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const addToast = useToastStore((s) => s.addToast);
  const canInstall = canInstallPacks(useAuthStore((s) => s.userRole));
  const { list, entries, activeSlug, activeSource, names } = usePackCatalogData();
  const bandLabels = useBandLabels();
  const entry = useMemo(() => entries.find((e) => e.slug === slug) ?? null, [entries, slug]);
  const isActive = entry !== null && entry.slug === activeSlug;
  const envPinned = activeSource === 'env';
  const preview = useApplyPreview(entry ? slug : null);
  const plan = preview.data?.plan;

  const [applyOpen, setApplyOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);

  const backTo =
    typeof (location.state as { backTo?: unknown } | null)?.backTo === 'string'
      ? (location.state as { backTo: string }).backTo
      : '/packs';

  // ``?setup=1``: open the setup dialog once, when there is something to set up.
  const wantsSetup = searchParams.get('setup') === '1';
  useEffect(() => {
    if (!wantsSetup || !entry) return;
    if (canInstall && !isActive && !envPinned) setApplyOpen(true);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('setup');
        return next;
      },
      { replace: true },
    );
  }, [wantsSetup, entry, canInstall, isActive, envPinned, setSearchParams]);

  const fmtInt = useMemo(() => {
    try {
      return new Intl.NumberFormat(i18n.language || 'en');
    } catch {
      return new Intl.NumberFormat('en');
    }
  }, [i18n.language]);

  if (list.isLoading) {
    return (
      <div className="space-y-5" aria-busy="true">
        <div className="h-4 w-40 animate-pulse rounded bg-surface-secondary" />
        <div className="h-40 animate-pulse rounded-2xl bg-surface-secondary" />
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="h-72 animate-pulse rounded-xl bg-surface-secondary" />
          <div className="h-72 animate-pulse rounded-xl bg-surface-secondary" />
        </div>
      </div>
    );
  }

  if (list.isError && !list.data) {
    return (
      <div role="alert" className="py-16 text-center">
        <AlertTriangle size={36} className="mx-auto mb-3 text-semantic-warning" strokeWidth={1.5} aria-hidden />
        <p className="text-sm font-medium text-content-primary">
          {t('modules.packs_load_failed', { defaultValue: 'Failed to load packs' })}
        </p>
        <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />} onClick={() => void list.refetch()} className="mt-4">
          {t('common.retry', { defaultValue: 'Retry' })}
        </Button>
      </div>
    );
  }

  if (!entry) {
    return (
      <div className="py-16 text-center" data-testid="pack-not-found">
        <PackageX size={40} className="mx-auto mb-3 text-content-tertiary" strokeWidth={1.5} aria-hidden />
        <p className="text-sm font-medium text-content-primary">
          {t('packs.not_found', { defaultValue: 'This pack is not installed here' })}
        </p>
        <p className="mt-1 font-mono text-xs text-content-tertiary">{slug}</p>
        <Link to="/packs" className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue hover:underline">
          <ArrowLeft size={14} aria-hidden className="rtl:rotate-180" />
          {t('packs.all_packs', { defaultValue: 'All packs' })}
        </Link>
      </div>
    );
  }

  const { pack } = entry;
  const meta = PACK_TYPE_META[entry.type];
  const TypeIcon = meta.icon;
  const description = t(`modules.pp_desc_${packNameSlug(pack.slug)}`, { defaultValue: pack.description });
  const regulatorRefs = asStringArray(pack.metadata.regulator_refs);
  const supportEmail = typeof pack.metadata.support_email === 'string' ? pack.metadata.support_email : null;
  const accent = pack.branding.accent_color ?? pack.branding.primary_color;
  const moduleName = (id: string) => presetModuleName(t, i18n.language, id);
  const languageList = entry.languages.map((l) => names.languageName(l) ?? l.toUpperCase());

  let primaryAction: React.ReactNode = null;
  if (canInstall && envPinned) {
    primaryAction = (
      <p className="inline-flex items-center gap-1.5 text-xs text-content-tertiary">
        <Info size={13} aria-hidden />
        {t('modules.pack_active_via_env', { defaultValue: 'Active via environment (OE_PACK)' })}
      </p>
    );
  } else if (canInstall) {
    primaryAction = isActive ? (
      <Button variant="secondary" icon={<Power size={15} />} onClick={() => setDeactivateOpen(true)} data-testid="pack-detail-deactivate">
        {t('modules.pack_deactivate', { defaultValue: 'Deactivate' })}
      </Button>
    ) : (
      <Button
        variant="primary"
        icon={<Power size={15} />}
        onClick={() => {
          if (envPinned) {
            addToast({
              type: 'warning',
              title: t('modules.pack_active_via_env', { defaultValue: 'Active via environment (OE_PACK)' }),
            });
            return;
          }
          setApplyOpen(true);
        }}
        data-testid="pack-detail-activate"
      >
        {t('modules.pack_activate', { defaultValue: 'Activate pack' })}
      </Button>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.packs', { defaultValue: 'Packs' }), to: '/packs' },
          { label: entry.name },
        ]}
      />
      <Link
        to={backTo}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-content-secondary hover:text-content-primary"
        data-testid="pack-detail-back"
      >
        <ArrowLeft size={15} aria-hidden className="rtl:rotate-180" />
        {t('packs.all_packs', { defaultValue: 'All packs' })}
      </Link>

      {/* Hero */}
      <section className="relative overflow-hidden rounded-2xl border border-border-light bg-surface-elevated p-5 shadow-sm sm:p-6">
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.06] dark:opacity-[0.12]"
          style={{ background: `linear-gradient(120deg, ${pack.branding.primary_color} 0%, ${accent} 50%, transparent 80%)` }}
        />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-start">
          <PackEmblem pack={pack} size={72} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex h-6 items-center gap-1 rounded-md bg-surface-secondary px-2 text-2xs font-semibold uppercase tracking-wide text-content-secondary">
                <TypeIcon size={12} aria-hidden style={{ color: accent }} />
                {t(meta.labelKey, { defaultValue: meta.defaultLabel })}
              </span>
              {isActive && (
                <span className="inline-flex h-6 items-center gap-1 rounded-md bg-semantic-success-bg px-2 text-2xs font-semibold text-semantic-success">
                  <Check size={12} aria-hidden />
                  {t('modules.active', { defaultValue: 'Active' })}
                </span>
              )}
            </div>
            <h1 className="mt-2 text-2xl font-bold tracking-tight text-content-primary">{entry.name}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-content-tertiary">
              {entry.country && <CountryFlag code={entry.country} size={18} className="rounded-sm" />}
              <span>{entry.countryName ? `${entry.countryName} · ${bandLabels[entry.region]}` : bandLabels[entry.region]}</span>
              <span aria-hidden>·</span>
              <span className="font-mono text-xs">v{pack.pack_version}</span>
            </p>
            <p className="mt-3 max-w-3xl text-sm leading-relaxed text-content-secondary">{description}</p>
          </div>
          <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">{primaryAction}</div>
        </div>
      </section>

      <ViewerPackNotice />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {/* What changes */}
        <div className="min-w-0 space-y-4">
          <h2 className="text-base font-semibold text-content-primary">
            {isActive
              ? t('packs.what_it_changed', { defaultValue: 'What this pack changed' })
              : t('packs.what_changes', { defaultValue: 'What activating changes' })}
          </h2>
          {preview.isLoading ? (
            <div className="space-y-4" aria-busy="true">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-28 animate-pulse rounded-xl bg-surface-secondary" />
              ))}
            </div>
          ) : preview.isError || !plan ? (
            <div role="alert" className="rounded-xl border border-border-light bg-surface-elevated p-6 text-center">
              <AlertTriangle size={28} className="mx-auto mb-2 text-semantic-warning" strokeWidth={1.5} aria-hidden />
              <p className="text-sm text-content-secondary">
                {t('packs.preview_failed', { defaultValue: 'The preview of this pack could not be loaded.' })}
              </p>
              <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />} onClick={() => void preview.refetch()} className="mt-3">
                {t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            </div>
          ) : (
            <>
              <Section icon={Languages} title={t('packs.sec_locale', { defaultValue: 'Currency and language' })} testId="pack-detail-locale">
                <dl className="divide-y divide-border-light">
                  <Fact label={t('packs.currency', { defaultValue: 'Currency' })}>
                    <span className="font-mono">{plan.default_currency}</span>
                  </Fact>
                  <Fact label={t('packs.languages', { defaultValue: 'Languages' })}>{languageList.join(', ')}</Fact>
                  {plan.default_tax_template && (
                    <Fact label={t('packs.tax_template', { defaultValue: 'Tax template' })}>
                      <span className="font-mono text-xs">{plan.default_tax_template}</span>
                    </Fact>
                  )}
                  {plan.built_in_for_country?.vat?.standard && (
                    <Fact label={t('packs.vat_standard', { defaultValue: 'Standard VAT rate' })}>
                      {plan.built_in_for_country.vat.standard}
                    </Fact>
                  )}
                  {plan.built_in_for_country?.einvoice && (
                    <Fact label={t('packs.einvoice', { defaultValue: 'E-invoicing' })}>
                      {plan.built_in_for_country.einvoice.label}
                    </Fact>
                  )}
                </dl>
              </Section>

              <Section icon={Boxes} title={t('packs.modules', { defaultValue: 'Modules' })} testId="pack-detail-modules">
                {plan.modules_to_enable.length === 0 && plan.modules_to_disable.length === 0 ? (
                  <p className="text-sm text-content-secondary">
                    {t('packs.modules_unchanged', { defaultValue: 'Leaves your modules as they are. Every module stays available.' })}
                  </p>
                ) : (
                  <div className="space-y-3">
                    {plan.modules_to_enable.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-xs font-medium text-content-secondary">
                          {t('packs.modules_on_n', { defaultValue: 'Switched on: {{n}}', n: plan.modules_to_enable.length })}
                        </p>
                        <Chips items={plan.modules_to_enable.map(moduleName)} tone="on" />
                      </div>
                    )}
                    {plan.modules_to_disable.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-xs font-medium text-content-secondary">
                          {t('packs.modules_off_n', { defaultValue: 'Hidden: {{n}}', n: plan.modules_to_disable.length })}
                        </p>
                        <Chips items={plan.modules_to_disable.map(moduleName)} tone="off" />
                      </div>
                    )}
                  </div>
                )}
              </Section>

              <Section icon={ShieldCheck} title={t('packs.sec_validation', { defaultValue: 'Validation rules' })} testId="pack-detail-rules">
                {plan.rule_packs_active.length === 0 && (plan.rule_sets_enabled ?? []).length === 0 ? (
                  <p className="text-sm text-content-secondary">
                    {t('packs.rules_none', { defaultValue: 'No extra rule sets. The platform’s standard checks keep running.' })}
                  </p>
                ) : (
                  <div className="space-y-3">
                    {(plan.rule_sets_enabled ?? []).length > 0 && (
                      <div>
                        <p className="mb-1.5 text-xs font-medium text-content-secondary">
                          {t('packs.rule_sets_on', { defaultValue: 'Rule sets switched on for new projects' })}
                        </p>
                        <Chips items={plan.rule_sets_enabled ?? []} />
                      </div>
                    )}
                    {plan.rule_packs_active.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-xs font-medium text-content-secondary">
                          {t('packs.rule_packs_enforced', { defaultValue: 'Rules the engine enforces' })}
                        </p>
                        <Chips items={plan.rule_packs_active} />
                      </div>
                    )}
                  </div>
                )}
              </Section>

              <Section icon={Database} title={t('packs.sec_cost_bases', { defaultValue: 'Cost databases' })} testId="pack-detail-costs">
                {(plan.cost_bases ?? []).length === 0 ? (
                  <p className="text-sm text-content-secondary">
                    {t('packs.cost_bases_none', { defaultValue: 'This pack loads no cost database.' })}
                  </p>
                ) : (
                  <ul className="divide-y divide-border-light">
                    {(plan.cost_bases ?? []).map((base) => (
                      <li key={base.slug} className="flex items-center gap-3 py-2">
                        {base.flag && /^[a-z]{2}$/i.test(base.flag) ? (
                          <CountryFlag code={base.flag.toLowerCase()} size={20} className="rounded-sm" />
                        ) : (
                          <Database size={16} aria-hidden className="text-content-tertiary" />
                        )}
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm text-content-primary">
                            {(base.flag && names.countryName(base.flag)) || base.market || base.slug}
                            {base.currency && <span className="ms-1.5 font-mono text-xs text-content-tertiary">{base.currency}</span>}
                          </p>
                          {base.positions !== null && (
                            <p className="text-xs text-content-tertiary">
                              {t('packs.work_items_n', { defaultValue: 'Work items: {{n}}', n: fmtInt.format(base.positions) })}
                            </p>
                          )}
                        </div>
                        {base.loadable ? (
                          <span className="rounded-md bg-semantic-success-bg px-1.5 py-0.5 text-2xs font-medium text-semantic-success">
                            {t('packs.cost_base_ready', { defaultValue: 'Ready to load' })}
                          </span>
                        ) : (
                          <span className="rounded-md bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-tertiary">
                            {t('packs.cost_base_unavailable', { defaultValue: 'Not published yet' })}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section icon={FolderKanban} title={t('packs.demo_projects', { defaultValue: 'Demo projects' })} testId="pack-detail-demos">
                {!plan.demo_project && (pack.demo_template_ids ?? []).length === 0 ? (
                  <p className="text-sm text-content-secondary">
                    {t('packs.demo_none', { defaultValue: 'This pack ships no demo project.' })}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {plan.demo_project && (
                      <div className="rounded-lg bg-surface-secondary/60 p-3">
                        <p className="text-sm font-medium text-content-primary">
                          {plan.demo_project.name ?? plan.demo_project.demo_id}
                        </p>
                        <p className="mt-0.5 text-xs text-content-tertiary">
                          {[
                            plan.demo_project.currency,
                            plan.demo_project.classification_standard,
                            plan.demo_project.positions !== undefined
                              ? t('packs.positions_n', { defaultValue: 'Positions: {{n}}', n: fmtInt.format(plan.demo_project.positions) })
                              : null,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                        <p className="mt-1 text-2xs text-content-tertiary">
                          {t('packs.demo_installed_on_activate', { defaultValue: 'Installed when you activate the pack.' })}
                        </p>
                      </div>
                    )}
                    {(pack.demo_template_ids ?? []).length > 0 && (
                      <p className="text-xs text-content-tertiary">
                        {t('packs.demo_n', { defaultValue: 'Demo projects: {{n}}', n: (pack.demo_template_ids ?? []).length })}
                      </p>
                    )}
                  </div>
                )}
              </Section>

              {preview.data && preview.data.plan.warnings.length > 0 && (
                <div role="note" className="rounded-xl border border-semantic-warning/40 bg-semantic-warning-bg p-4 text-sm text-content-primary">
                  <ul className="list-disc space-y-1 ps-5">
                    {preview.data.plan.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>

        {/* At a glance */}
        <aside className="min-w-0 space-y-4">
          <Section icon={Info} title={t('packs.at_a_glance', { defaultValue: 'At a glance' })}>
            <dl className="divide-y divide-border-light">
              <Fact label={t('packs.type_label', { defaultValue: 'Pack type' })}>
                {t(meta.labelKey, { defaultValue: meta.defaultLabel })}
              </Fact>
              <Fact label={t('packs.region_label', { defaultValue: 'Region' })}>{bandLabels[entry.region]}</Fact>
              <Fact label={t('packs.currency', { defaultValue: 'Currency' })}>
                <span className="font-mono">{pack.default_currency}</span>
              </Fact>
              <Fact label={t('packs.languages', { defaultValue: 'Languages' })}>{languageList.join(', ')}</Fact>
              {entry.standards.length > 0 && (
                <Fact label={t('packs.standards', { defaultValue: 'Standards' })}>{entry.standards.join(', ')}</Fact>
              )}
              <Fact label={t('packs.modules', { defaultValue: 'Modules' })}>
                {entry.moduleCount === null
                  ? t('packs.modules_all', { defaultValue: 'Keeps all modules' })
                  : t('packs.modules_n', { defaultValue: 'Modules: {{n}}', n: entry.moduleCount })}
              </Fact>
              <Fact label={t('packs.version', { defaultValue: 'Version' })}>
                <span className="font-mono">{pack.pack_version}</span>
              </Fact>
            </dl>
          </Section>

          {regulatorRefs.length > 0 && (
            <Section icon={ShieldCheck} title={t('modules.partner_pack_standards', { defaultValue: 'Reference standards' })}>
              <ul className="space-y-1.5 text-xs text-content-secondary">
                {regulatorRefs.map((ref) => (
                  <li key={ref} className="flex gap-2">
                    <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-content-tertiary" />
                    <span>{ref}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-2xs leading-snug text-content-tertiary">
                {t('modules.partner_pack_standards_note', {
                  defaultValue: 'Listed for reference. Enforced validation rules are shown when you activate the pack.',
                })}
              </p>
            </Section>
          )}

          {(pack.partner_url || supportEmail) && (
            <div className="flex flex-col gap-2 text-sm">
              {pack.partner_url && (
                <a href={pack.partner_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 font-medium text-oe-blue hover:underline">
                  <ExternalLink size={14} aria-hidden />
                  {t('modules.partner_pack_website', { defaultValue: 'Website' })}
                </a>
              )}
              {supportEmail && (
                <a href={`mailto:${supportEmail}`} className="inline-flex items-center gap-1.5 text-content-secondary hover:underline">
                  <Mail size={14} aria-hidden />
                  {supportEmail}
                </a>
              )}
            </div>
          )}
        </aside>
      </div>

      <PartnerPackApplyDialog
        open={applyOpen}
        onClose={() => setApplyOpen(false)}
        slug={pack.slug}
        partnerName={pack.partner_name}
      />
      {isActive && (
        <PartnerPackDeactivateDialog
          open={deactivateOpen}
          onClose={() => setDeactivateOpen(false)}
          partnerName={pack.partner_name}
        />
      )}
    </div>
  );
}

export default PackDetailPage;
