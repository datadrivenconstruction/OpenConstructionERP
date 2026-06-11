import { useState, useMemo, useEffect, useCallback, useRef, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, Link, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  Search,
  Database,
  Sparkles,
  Globe,
  FileInput,
  BarChart3,
  Plug,
  Package,
  Check,
  Download,
  ShieldCheck,
  Building2,
  Boxes,
  Loader2,
  Settings,
  AlertTriangle,
  Trash2,
  RefreshCw,
  Info,
  Calculator,
  ClipboardList,
  Pencil,
  Users,
  Layers,
  Server,
  ExternalLink,
  Mail,
  Power,
  BookOpen,
  Home,
  HardHat,
  Briefcase,
  Box,
  UploadCloud,
  FileArchive,
  type LucideIcon,
} from 'lucide-react';
import { Card, Badge, Button, Input, InfoHint, Breadcrumb, ConfirmDialog, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { PartnerPackApplyDialog } from './PartnerPackApplyDialog';
import { PartnerPackDeactivateDialog } from './PartnerPackDeactivateDialog';
import {
  useAppliedPack,
  useInstallPack,
  useRescanPacks,
  MAX_PACK_UPLOAD_BYTES,
} from './partnerPacks';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { getModulesByCategory } from '@/modules/_registry';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface MarketplaceModule {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  version: string;
  size_mb: number;
  author: string;
  tags: string[];
  requires: string[];
  installed: boolean;
  price: string;
}

interface SystemModule {
  name: string;
  version: string;
  display_name: string;
  display_name_i18n?: Record<string, string>;
  description?: string;
  author?: string;
  category: string;
  depends: string[];
  optional_depends?: string[];
  has_router: boolean;
  loaded: boolean;
  enabled: boolean;
  is_core: boolean;
}

interface CompanyPresetAPI {
  key: string;
  label: string;
  description: string;
  icon: string;
  enabled_modules: string[];
  module_count: number;
}

interface PartnerPackBranding {
  primary_color: string;
  accent_color: string | null;
  has_logo: boolean;
  has_favicon: boolean;
  powered_by_text: string;
}

interface PartnerPackManifestAPI {
  slug: string;
  partner_name: string;
  partner_url: string | null;
  pack_version: string;
  description: string;
  default_locale: string;
  additional_locales: string[];
  cwicr_regions: string[];
  default_currency: string;
  default_tax_template: string | null;
  validation_rule_packs: string[];
  default_modules: string[];
  hidden_modules: string[];
  branding: PartnerPackBranding;
  has_onboarding_script: boolean;
  metadata: Record<string, unknown>;
}

interface PartnerPacksResponse {
  active_slug: string | null;
  installed: PartnerPackManifestAPI[];
}

/* ── Tab definitions ───────────────────────────────────────────────────── */

const MODULE_TAB_IDS = ['profiles', 'partner-packs', 'data-packages', 'system'] as const;
type TabKey = (typeof MODULE_TAB_IDS)[number];

const TABS: { key: TabKey; labelKey: string; defaultLabel: string; icon: LucideIcon }[] = [
  { key: 'profiles', labelKey: 'modules.tab_profiles', defaultLabel: 'Company Profiles', icon: Users },
  { key: 'partner-packs', labelKey: 'modules.tab_partner_packs', defaultLabel: 'Partner Packs', icon: Building2 },
  { key: 'data-packages', labelKey: 'modules.tab_data_packages', defaultLabel: 'Data Packages', icon: Layers },
  { key: 'system', labelKey: 'modules.tab_system', defaultLabel: 'System Modules', icon: Server },
];

/* ── Marketplace category config ───────────────────────────────────────── */

type CategoryKey =
  | 'all'
  | 'demo_project'
  | 'resource_catalog'
  | 'cost_database'
  | 'vector_index'
  | 'language'
  | 'converter'
  | 'analytics'
  | 'integration';

interface CategoryMeta {
  labelKey: string;
  defaultLabel: string;
  icon: LucideIcon;
}

const CATEGORIES: Record<CategoryKey, CategoryMeta> = {
  all: { labelKey: 'marketplace.category_all', defaultLabel: 'All', icon: Package },
  demo_project: { labelKey: 'marketplace.category_demo', defaultLabel: 'Demo Projects', icon: Building2 },
  resource_catalog: { labelKey: 'marketplace.category_resource_catalog', defaultLabel: 'Resource Catalogs', icon: Boxes },
  cost_database: { labelKey: 'marketplace.category_cost_database', defaultLabel: 'Cost Databases', icon: Database },
  vector_index: { labelKey: 'marketplace.category_vector_index', defaultLabel: 'Vector Indices', icon: Sparkles },
  language: { labelKey: 'marketplace.category_language', defaultLabel: 'Languages', icon: Globe },
  converter: { labelKey: 'marketplace.category_converter', defaultLabel: 'Converters', icon: FileInput },
  analytics: { labelKey: 'marketplace.category_analytics', defaultLabel: 'Analytics', icon: BarChart3 },
  integration: { labelKey: 'marketplace.category_integration', defaultLabel: 'Integrations', icon: Plug },
};

const CATEGORY_KEYS = Object.keys(CATEGORIES) as CategoryKey[];

/* ── Helpers ───────────────────────────────────────────────────────────── */

const ICON_MAP: Record<string, LucideIcon> = {
  Database, Sparkles, Globe, FileInput, BarChart3, Plug, Building2, Boxes,
  Calculator, ClipboardList, Pencil,
};

function getModuleIcon(iconName: string): LucideIcon {
  return ICON_MAP[iconName] ?? Package;
}

function formatModuleId(id: string): string {
  return id.split('-').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function formatSize(sizeMb: number): string {
  if (sizeMb < 1) return `${Math.round(sizeMb * 1024)} KB`;
  if (sizeMb >= 1024) return `${(sizeMb / 1024).toFixed(1)} GB`;
  return `${sizeMb.toFixed(1)} MB`;
}

/* ── Module category display config ────────────────────────────────────── */

const MODULE_CATEGORY_ORDER = [
  'core',
  'estimation',
  'planning',
  'procurement',
  'finance',
  'commercial',
  'contracts',
  'bim',
  'ai',
  'analytics',
  'quality',
  'safety',
  'field',
  'communication',
  'documentation',
  'integration',
  'converter',
  'tools',
  'regional',
] as const;

const MODULE_CATEGORY_META: Record<string, { labelKey: string; defaultLabel: string }> = {
  core: { labelKey: 'modules.cat_core', defaultLabel: 'Core' },
  estimation: { labelKey: 'nav.group_estimation', defaultLabel: 'Estimation' },
  planning: { labelKey: 'nav.group_planning', defaultLabel: 'Planning' },
  procurement: { labelKey: 'nav.group_procurement', defaultLabel: 'Procurement' },
  finance: { labelKey: 'modules.cat_finance', defaultLabel: 'Finance' },
  commercial: { labelKey: 'modules.cat_commercial', defaultLabel: 'Commercial' },
  contracts: { labelKey: 'modules.cat_contracts', defaultLabel: 'Contracts' },
  bim: { labelKey: 'modules.cat_bim', defaultLabel: 'BIM' },
  ai: { labelKey: 'modules.cat_ai', defaultLabel: 'AI' },
  analytics: { labelKey: 'modules.cat_analytics', defaultLabel: 'Analytics' },
  quality: { labelKey: 'modules.cat_quality', defaultLabel: 'Quality' },
  safety: { labelKey: 'modules.cat_safety', defaultLabel: 'Safety' },
  field: { labelKey: 'modules.cat_field', defaultLabel: 'Field Operations' },
  communication: { labelKey: 'modules.cat_communication', defaultLabel: 'Communication' },
  documentation: { labelKey: 'modules.cat_documentation', defaultLabel: 'Documentation' },
  integration: { labelKey: 'modules.cat_integration', defaultLabel: 'Integration' },
  converter: { labelKey: 'modules.cat_converter', defaultLabel: 'CAD / BIM Converters' },
  tools: { labelKey: 'nav.group_tools', defaultLabel: 'Tools' },
  regional: { labelKey: 'modules.cat_regional', defaultLabel: 'Regional Standards' },
};

/* ── Preset icon mapping ───────────────────────────────────────────────── */

const PRESET_ICON_MAP: Record<string, LucideIcon> = {
  Building2, Calculator, ClipboardList, Pencil, Boxes,
  Home, HardHat, Briefcase, Box,
};

function getPresetIcon(iconName: string): LucideIcon {
  return PRESET_ICON_MAP[iconName] ?? Package;
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* ── Main component ──────────────────────────────────────────────────── */
/* ══════════════════════════════════════════════════════════════════════════ */

export function ModulesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // Deep-link support: ``/modules?tab=partner-packs`` opens that tab directly
  // (used by the dashboard co-brand banner). Falls back to Company Profiles.
  const [activeTab, setActiveTab] = useState<TabKey>(() => {
    const tab = searchParams.get('tab');
    return tab && (MODULE_TAB_IDS as readonly string[]).includes(tab)
      ? (tab as TabKey)
      : 'profiles';
  });
  const onTabKeyDown = useTabKeyboardNav<TabKey>({
    ids: MODULE_TAB_IDS,
    activeId: activeTab,
    onChange: setActiveTab,
    orientation: 'horizontal',
  });

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.modules', 'Modules') }]} />

      {/* Header */}
      <PageHeader
        className="animate-card-in"
        srTitle={t('nav.modules', 'Modules')}
        subtitle={t('modules.page_subtitle', {
          defaultValue: 'Manage your company profile, data packages, and system modules.',
        })}
        actions={
          <Link
            to="/modules/developer-guide"
            className="inline-flex items-center gap-2 h-9 px-3 rounded-lg border border-oe-blue/30 bg-oe-blue/5 text-xs font-medium text-oe-blue hover:bg-oe-blue/10 hover:border-oe-blue/50 transition-colors shrink-0"
            title={t('modules.dev_guide_hint', {
              defaultValue: 'Learn how to build your own module',
            })}
          >
            <Info size={14} />
            {t('modules.dev_guide', { defaultValue: 'Build a module - developer guide' })}
          </Link>
        }
      />

      {/* Canonical module intro — pain-named, copy from MODULE_INTRO_COPY. */}
      <DismissibleInfo
        storageKey="modules"
        title={t('modules.intro_title', {
          defaultValue: 'Show only the tools this company needs',
        })}
        more={
          t('modules.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('modules.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.setup_databases', { defaultValue: 'Databases & Resources' }),
            onClick: () => navigate('/setup/databases'),
          },
          {
            label: t('modules.dev_guide', { defaultValue: 'Developer guide' }),
            onClick: () => navigate('/modules/developer-guide'),
          },
          { label: t('nav.settings', { defaultValue: 'Settings' }), onClick: () => navigate('/settings') },
        ]}
      >
        {t('modules.intro_body', {
          defaultValue:
            'Switch on a company profile to tailor which modules appear in the sidebar, apply a partner pack to load a branded preset of presets and rules, and install data packages like cost databases, resource catalogues and languages from the marketplace. System modules lists everything currently loaded so you can see what is active and what an install would add.',
        })}
      </DismissibleInfo>

      {/* Tab bar */}
      <div
        className="flex gap-1 rounded-lg bg-surface-secondary p-1 animate-card-in"
        role="tablist"
        aria-label={t('modules.tabs', { defaultValue: 'Module sections' })}
        onKeyDown={onTabKeyDown}
        style={{ animationDelay: '30ms' }}
      >
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              role="tab"
              id={`modules-tab-${tab.key}`}
              aria-selected={isActive}
              aria-controls={`modules-panel-${tab.key}`}
              tabIndex={isActive ? 0 : -1}
              className={clsx(
                'flex-1 inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all duration-fast',
                isActive
                  ? 'bg-surface-elevated text-content-primary shadow-xs'
                  : 'text-content-secondary hover:text-content-primary',
              )}
            >
              <Icon size={16} />
              {t(tab.labelKey, { defaultValue: tab.defaultLabel })}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div
        role="tabpanel"
        id={`modules-panel-${activeTab}`}
        aria-labelledby={`modules-tab-${activeTab}`}
      >
        {activeTab === 'profiles' && <CompanyProfilesTab />}
        {activeTab === 'partner-packs' && <PartnerPacksTab />}
        {activeTab === 'data-packages' && <DataPackagesTab />}
        {activeTab === 'system' && <SystemModulesTab />}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* ── Tab 1: Company Profiles ─────────────────────────────────────────── */
/* ══════════════════════════════════════════════════════════════════════════ */

function CompanyProfilesTab() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { isModuleEnabled, setModuleEnabled, canDisable, getEnabledDependents, syncFromServer } =
    useModuleStore();

  const [switchingTo, setSwitchingTo] = useState<CompanyPresetAPI | null>(null);
  const [isSwitching, setIsSwitching] = useState(false);

  // Determine active profile from localStorage
  const [activeProfileKey, setActiveProfileKey] = useState<string | null>(() => {
    try {
      return localStorage.getItem('oe_company_type') ?? null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    void syncFromServer();
  }, [syncFromServer]);

  const {
    data: presets,
    isLoading: presetsLoading,
    isError: presetsError,
    refetch: refetchPresets,
  } = useQuery({
    queryKey: ['onboarding-presets'],
    queryFn: () => apiGet<CompanyPresetAPI[]>('/v1/users/onboarding-presets/'),
  });

  const handleProfileClick = useCallback(
    (preset: CompanyPresetAPI) => {
      if (preset.key === activeProfileKey) return;
      setSwitchingTo(preset);
    },
    [activeProfileKey],
  );

  const confirmSwitch = useCallback(async () => {
    if (!switchingTo) return;
    setIsSwitching(true);
    try {
      // ── Single authoritative write path ──────────────────────────────
      // The onboarding endpoint persists company_type + completed AND syncs
      // module_preferences server-side from `enabled_modules`. We deliberately
      // do NOT optimistically loop setModuleEnabled() here: that scheduled a
      // second, debounced PATCH to /me/module-preferences/ which raced this
      // POST on the SAME metadata.module_preferences JSON (last writer won,
      // sometimes with the stale store snapshot). One awaited write, then a
      // read-back, keeps the two in lockstep.
      const isFullEnterprise = switchingTo.key === 'full_enterprise';
      const enabledModules = isFullEnterprise
        ? Object.values(getModulesByCategory()).flatMap((mods) => mods.map((m) => m.id))
        : switchingTo.enabled_modules;

      await apiPost('/v1/users/me/onboarding/', {
        company_type: switchingTo.key,
        enabled_modules: enabledModules,
        interface_mode: 'advanced',
        completed: true,
      });

      // Reconcile the local module store from the server's canonical
      // module_preferences (set by the POST above). syncFromServer() updates
      // localStorage + the reactive store WITHOUT scheduling another server
      // write, so the sidebar reflects the new profile immediately and there
      // is no trailing debounced PATCH to race. We await it before the toast
      // so success only shows once everything has actually landed.
      await syncFromServer();

      // Store profile key locally
      localStorage.setItem('oe_company_type', switchingTo.key);
      setActiveProfileKey(switchingTo.key);

      addToast({
        type: 'success',
        title: t('modules.profile_switched', {
          defaultValue: 'Profile switched to {{name}}',
          name: switchingTo.label,
        }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('modules.profile_switch_failed', { defaultValue: 'Failed to switch profile' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsSwitching(false);
      setSwitchingTo(null);
    }
  }, [switchingTo, syncFromServer, addToast, t]);

  const activePreset = presets?.find((p) => p.key === activeProfileKey);
  const activeModuleCount = activePreset?.module_count ?? 0;

  return (
    <div className="animate-card-in" style={{ animationDelay: '60ms' }}>
      {/* Current profile banner */}
      {activePreset && (
        <div className="mb-6 rounded-xl border border-oe-blue/20 bg-oe-blue-subtle px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                {(() => { const Icon = getPresetIcon(activePreset.icon); return <Icon size={20} />; })()}
              </div>
              <div>
                <p className="text-sm font-semibold text-content-primary">
                  {t('modules.current_profile', { defaultValue: 'Current Profile' })}:{' '}
                  {t(`onboarding.company_${activePreset.key}`, { defaultValue: activePreset.label })}
                </p>
                <p className="text-xs text-content-secondary">
                  {activeModuleCount} {t('modules.modules_active_label', { defaultValue: 'modules active' })}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Profile cards grid */}
      <h2 className="text-sm font-semibold text-content-secondary uppercase tracking-wider mb-3">
        {t('modules.choose_profile', { defaultValue: 'Company Profiles' })}
      </h2>

      {presetsLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Card key={i} className="animate-pulse" padding="sm">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-surface-secondary" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-2/3 rounded bg-surface-secondary" />
                  <div className="h-3 w-full rounded bg-surface-secondary" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : presetsError ? (
        <div className="py-12 text-center">
          <AlertTriangle size={36} className="mx-auto mb-3 text-semantic-warning" strokeWidth={1.5} />
          <p className="text-sm font-medium text-content-secondary">
            {t('modules.profiles_load_failed', { defaultValue: 'Failed to load profiles' })}
          </p>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw size={14} />}
            onClick={() => void refetchPresets()}
            className="mt-3"
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      ) : !presets || presets.length === 0 ? (
        <div className="py-12 text-center">
          <Users size={36} className="mx-auto mb-3 text-content-tertiary" />
          <p className="text-sm font-medium text-content-secondary">
            {t('modules.no_profiles', { defaultValue: 'No company profiles available' })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('modules.no_profiles_hint', { defaultValue: 'Profiles help pre-configure which modules are active for your company type.' })}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {presets?.map((preset) => {
            const Icon = getPresetIcon(preset.icon);
            const isActive = preset.key === activeProfileKey;
            return (
              <button
                key={preset.key}
                onClick={() => handleProfileClick(preset)}
                aria-label={`${t(`onboarding.company_${preset.key}`, { defaultValue: preset.label })} - ${preset.module_count} ${t('modules.modules_label', { defaultValue: 'modules' })}`}
                aria-pressed={isActive}
                className={clsx(
                  'text-left rounded-xl border p-4 transition-all',
                  isActive
                    ? 'border-oe-blue bg-oe-blue-subtle ring-1 ring-oe-blue/30'
                    : 'border-border-light bg-surface-elevated hover:border-border hover:shadow-xs',
                )}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={clsx(
                      'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
                      isActive ? 'bg-oe-blue/10 text-oe-blue' : 'bg-surface-secondary text-content-secondary',
                    )}
                  >
                    <Icon size={20} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-content-primary">{t(`onboarding.company_${preset.key}`, { defaultValue: preset.label })}</span>
                      {isActive && (
                        <Badge variant="success" size="sm">
                          <Check size={10} className="mr-0.5" />
                          {t('modules.active', { defaultValue: 'Active' })}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-content-secondary line-clamp-2">
                      {t(`onboarding.company_${preset.key}_desc`, { defaultValue: preset.description })}
                    </p>
                    <p className="mt-1.5 text-2xs text-content-tertiary font-medium">
                      {preset.module_count} {t('modules.modules_label', { defaultValue: 'modules' })}
                    </p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Active module toggles */}
      <div className="mt-10">
        <ModuleTogglesSection
          isModuleEnabled={isModuleEnabled}
          setModuleEnabled={setModuleEnabled}
          canDisable={canDisable}
          getEnabledDependents={getEnabledDependents}
        />
      </div>

      {/* Confirm dialog */}
      <ConfirmDialog
        open={switchingTo !== null}
        onConfirm={() => void confirmSwitch()}
        onCancel={() => setSwitchingTo(null)}
        title={t('modules.switch_profile_title', {
          defaultValue: 'Switch Profile',
        })}
        message={t('modules.switch_profile_message', {
          defaultValue: 'Switch to {{name}}? This will change your active modules to match this profile.',
          name: switchingTo?.label ?? '',
        })}
        confirmLabel={t('modules.switch_confirm', { defaultValue: 'Switch Profile' })}
        variant="warning"
        loading={isSwitching}
      />
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* ── Tab: Partner Packs ──────────────────────────────────────────────── */
/* ══════════════════════════════════════════════════════════════════════════ */

function PartnerPacksTab() {
  const { t } = useTranslation();

  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['partner-packs'],
    queryFn: () => apiGet<PartnerPacksResponse>('/v1/partner-pack/installed'),
    staleTime: 5 * 60 * 1000,
  });

  const applied = useAppliedPack();
  const packs = data?.installed ?? [];
  const activeSlug = data?.active_slug ?? null;
  const activeSource = applied.data?.applied ? applied.data.source ?? null : null;

  return (
    <div className="animate-card-in" style={{ animationDelay: '60ms' }}>
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-content-secondary uppercase tracking-wider mb-0.5">
          {t('modules.partner_packs_title', { defaultValue: 'Partner Packs' })}
        </h2>
        <p className="text-xs text-content-tertiary">
          {t('modules.partner_packs_desc_v2', {
            defaultValue:
              'Ready-made presets for a country or a partner: currency, tax template, validation standards and co-branding. Press Activate on a pack to apply it, and you can switch back any time.',
          })}
        </p>
        <Link
          to="/modules/developer-guide#partner-packs"
          className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-oe-blue hover:underline"
        >
          <BookOpen size={13} />
          {t('modules.partner_packs_build_own', {
            defaultValue: 'Build your own pack and share it with others',
          })}
        </Link>
      </div>

      {/* Install / rescan controls — admin only (gated inside the panel). */}
      <InstallPackPanel onChanged={() => void refetch()} />

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="animate-pulse" padding="sm">
              <div className="flex items-start gap-3">
                <div className="h-10 w-10 rounded-lg bg-surface-secondary" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-2/3 rounded bg-surface-secondary" />
                  <div className="h-3 w-full rounded bg-surface-secondary" />
                  <div className="h-3 w-1/2 rounded bg-surface-secondary" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : isError ? (
        <div className="py-16 text-center">
          <AlertTriangle size={40} className="mx-auto mb-3 text-semantic-warning" strokeWidth={1.5} />
          <p className="text-sm font-medium text-content-secondary">
            {t('modules.partner_packs_load_failed', { defaultValue: 'Failed to load partner packs' })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('modules.partner_packs_load_failed_hint', {
              defaultValue: 'Check your connection and try again.',
            })}
          </p>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw size={14} />}
            onClick={() => void refetch()}
            className="mt-4"
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      ) : packs.length === 0 ? (
        <div className="py-16 text-center">
          <Building2 size={40} className="mx-auto mb-3 text-content-tertiary" />
          <p className="text-sm font-medium text-content-secondary">
            {t('modules.no_partner_packs', { defaultValue: 'No partner packs available' })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('modules.no_partner_packs_hint', {
              defaultValue:
                'Partner packs ship pre-configured regional settings, validation standards, and branding for a specific market or partner.',
            })}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {packs.map((pack, i) => (
            <PartnerPackCard
              key={pack.slug}
              pack={pack}
              index={i}
              isActive={activeSlug === pack.slug}
              activeSource={activeSlug === pack.slug ? activeSource : null}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Install / Rescan panel ────────────────────────────────────────────── */

/**
 * Admin-only control strip for getting a partner pack onto this install:
 * upload a ``.zip`` (file picker or drag-and-drop) which POSTs to
 * ``/v1/partner-pack/install``, or Rescan ``<data-dir>/packs/`` for packs the
 * operator dropped in by hand. Non-admins see nothing — the underlying
 * endpoints are ``RequirePermission("admin")`` server-side, so we mirror that
 * gate here and never render a control that would only ever 403.
 *
 * ``onChanged`` is called after a successful install or rescan so the parent
 * tab can refetch the installed list; the install/rescan hooks also invalidate
 * the shared partner-pack query keys, so the grid updates immediately.
 */
export function InstallPackPanel({ onChanged }: { onChanged: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';

  const install = useInstallPack();
  const rescan = useRescanPacks();

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dropDescId = useId();

  // Only administrators can install or rescan packs (RequirePermission("admin")
  // on the backend). Render nothing for everyone else.
  if (!isAdmin) return null;

  const busy = install.isPending || rescan.isPending;

  /** Client-side guard: must be a .zip and under the 25 MiB cap before upload.
   *  Returns a human-readable reason string when rejected, or null when OK. */
  function rejectReason(file: File): string | null {
    const isZip =
      file.type === 'application/zip' ||
      file.type === 'application/x-zip-compressed' ||
      file.type === 'application/octet-stream' || // some browsers send this for .zip
      file.name.toLowerCase().endsWith('.zip');
    if (!isZip) {
      return t('modules.pack_install_not_zip', {
        defaultValue: 'Please choose a .zip file. Partner packs are distributed as a single .zip archive.',
      });
    }
    if (file.size > MAX_PACK_UPLOAD_BYTES) {
      return t('modules.pack_install_too_large', {
        defaultValue: 'That file is {{size}} MB. Partner packs must be 25 MB or smaller.',
        size: (file.size / (1024 * 1024)).toFixed(1),
      });
    }
    return null;
  }

  function handleFile(file: File | undefined | null) {
    if (!file) return;
    const reason = rejectReason(file);
    if (reason) {
      addToast({
        type: 'error',
        title: t('modules.pack_install_rejected', { defaultValue: "Can't install this file" }),
        message: reason,
      });
      return;
    }
    install.mutate(file, {
      onSuccess: (res) => {
        addToast({
          type: 'success',
          title: t('modules.pack_install_ok', { defaultValue: 'Pack installed' }),
          message: t('modules.pack_install_ok_msg', {
            defaultValue: '{{name}} ({{slug}}) v{{version}} is now available. Press Activate to apply it.',
            name: res.partner_name,
            slug: res.slug,
            version: res.pack_version,
          }),
        });
        onChanged();
      },
      onError: (err) => {
        // The backend ``detail`` is already user-safe; show it verbatim.
        addToast({
          type: 'error',
          title: t('modules.pack_install_failed', { defaultValue: 'Install failed' }),
          message: err instanceof Error ? err.message : String(err),
        });
      },
    });
  }

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    handleFile(e.target.files?.[0]);
    // Reset so picking the same file again re-fires change.
    e.target.value = '';
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
    if (busy) return;
    handleFile(e.dataTransfer.files?.[0]);
  }

  function handleRescan() {
    rescan.mutate(undefined, {
      onSuccess: (res) => {
        addToast({
          type: 'success',
          title: t('modules.pack_rescan_ok', { defaultValue: 'Rescan complete' }),
          message: t('modules.pack_rescan_count', {
            defaultValue: 'Found {{count}} packs.',
            count: res.count,
          }),
        });
        onChanged();
      },
      onError: (err) => {
        addToast({
          type: 'error',
          title: t('modules.pack_rescan_failed', { defaultValue: 'Rescan failed' }),
          message: err instanceof Error ? err.message : String(err),
        });
      },
    });
  }

  return (
    <Card className="mb-6 animate-card-in" padding="md" style={{ animationDelay: '40ms' }}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        {/* Dropzone + file picker */}
        <div className="min-w-0 flex-1">
          <div
            role="button"
            tabIndex={busy ? -1 : 0}
            aria-label={t('modules.pack_install_dropzone_label', {
              defaultValue: 'Upload a partner pack .zip - click to choose a file or drop one here',
            })}
            aria-describedby={dropDescId}
            aria-disabled={busy}
            onClick={() => {
              if (!busy) fileInputRef.current?.click();
            }}
            onKeyDown={(e) => {
              if (busy) return;
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onDrop}
            className={clsx(
              'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
              isDragging
                ? 'border-oe-blue bg-oe-blue/5'
                : 'border-border hover:border-oe-blue/50 hover:bg-surface-secondary/40',
              busy && 'cursor-not-allowed opacity-60',
            )}
          >
            {install.isPending ? (
              <Loader2 size={22} className="animate-spin text-oe-blue" />
            ) : (
              <UploadCloud size={22} className="text-content-tertiary" />
            )}
            <div>
              <p className="text-sm font-medium text-content-primary">
                {install.isPending
                  ? t('modules.pack_install_uploading', { defaultValue: 'Installing pack…' })
                  : t('modules.pack_install_cta', { defaultValue: 'Install a partner pack' })}
              </p>
              <p id={dropDescId} className="mt-0.5 text-xs text-content-tertiary">
                {t('modules.pack_install_hint', {
                  defaultValue: 'Click to choose a .zip, or drop one here. Max 25 MB. The pack is not activated until you Apply it.',
                })}
              </p>
            </div>
            {/* Hidden native input — the dropzone proxies clicks to it. */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,application/zip,application/x-zip-compressed"
              className="sr-only"
              aria-label={t('modules.pack_install_input_label', {
                defaultValue: 'Partner pack .zip file',
              })}
              disabled={busy}
              onChange={onInputChange}
            />
          </div>
        </div>

        {/* Rescan + drop-folder helper */}
        <div className="flex shrink-0 flex-col gap-2 sm:w-64">
          <Button
            variant="secondary"
            size="md"
            disabled={busy}
            icon={
              rescan.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )
            }
            onClick={handleRescan}
          >
            {rescan.isPending
              ? t('modules.pack_rescanning', { defaultValue: 'Rescanning…' })
              : t('modules.pack_rescan', { defaultValue: 'Rescan packs' })}
          </Button>
          <p className="flex items-start gap-1.5 text-2xs text-content-tertiary leading-relaxed">
            <FileArchive size={12} className="mt-0.5 shrink-0" />
            <span>
              {t('modules.pack_rescan_helper', {
                defaultValue:
                  'You can also drop a pack folder or .zip into your data dir under packs/ (next to the database), then click Rescan.',
              })}
            </span>
          </p>
        </div>
      </div>
    </Card>
  );
}

/* ── Partner Pack Card ─────────────────────────────────────────────────── */

interface PartnerPackCardProps {
  pack: PartnerPackManifestAPI;
  index: number;
  isActive: boolean;
  /** When the pack is active, whether it was applied in-app (can be
   *  deactivated from the UI) or pinned via the OE_PARTNER_PACK env var
   *  (managed by the operator, not unappliable here). */
  activeSource?: 'in-app' | 'env' | null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === 'string');
}

/* Two-letter monogram from the partner name, for the no-logo fallback. */
function packInitials(name: string): string {
  const words = name.trim().split(/[\s._-]+/).filter(Boolean);
  const letters =
    words.length >= 2
      ? `${words[0]?.[0] ?? ''}${words[1]?.[0] ?? ''}`
      : name.trim().slice(0, 2);
  return letters.toUpperCase() || '?';
}

/* The pack's app-icon emblem (served per-slug from the pack package).
   Falls back to a brand-gradient monogram built from the partner's own name,
   so a pack with no logo still gets a distinct mark - never our building icon. */
function PartnerPackLogo({ pack }: { pack: PartnerPackManifestAPI }) {
  const [errored, setErrored] = useState(false);
  const accent = pack.branding.accent_color ?? pack.branding.primary_color;

  if (errored) {
    return (
      <div
        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-base font-bold tracking-tight text-white shadow-sm"
        style={{
          background: `linear-gradient(135deg, ${pack.branding.primary_color}, ${accent})`,
        }}
      >
        {packInitials(pack.partner_name)}
      </div>
    );
  }

  return (
    <img
      src={`/api/v1/partner-pack/logo/${encodeURIComponent(pack.slug)}`}
      alt={`${pack.partner_name} logo`}
      className="h-12 w-12 shrink-0 rounded-xl object-contain shadow-sm"
      loading="lazy"
      onError={() => setErrored(true)}
    />
  );
}

function PartnerPackCard({ pack, index, isActive, activeSource }: PartnerPackCardProps) {
  const { t } = useTranslation();
  const [applyOpen, setApplyOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);

  const countryName =
    typeof pack.metadata.country_name_en === 'string'
      ? pack.metadata.country_name_en
      : null;
  const supportEmail =
    typeof pack.metadata.support_email === 'string'
      ? pack.metadata.support_email
      : null;
  const regulatorRefs = asStringArray(pack.metadata.regulator_refs);

  // Prefer human-readable regulator refs; fall back to raw rule-pack slugs.
  const standards = regulatorRefs.length > 0 ? regulatorRefs : pack.validation_rule_packs;

  const accent = pack.branding.accent_color ?? pack.branding.primary_color;

  return (
    <Card
      hoverable
      className="animate-card-in group relative overflow-hidden"
      style={{ animationDelay: `${80 + index * 30}ms` }}
    >
      {/* Brand accent — left border strip distinguishes each company */}
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-1 rounded-l-xl"
        style={{ backgroundColor: pack.branding.primary_color }}
      />

      <div className="pl-2">
        {/* Logo plate — the pack's own emblem with its name and version */}
        <div className="mb-3 flex items-center gap-3">
          <PartnerPackLogo pack={pack} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="truncate text-[15px] font-bold leading-tight text-content-primary">
                {pack.partner_name}
              </h3>
              {isActive && (
                <Badge variant="success" size="sm" className="shrink-0">
                  <Check size={10} className="mr-0.5" />
                  {t('modules.active', { defaultValue: 'Active' })}
                </Badge>
              )}
            </div>
            <div className="mt-1 flex items-center gap-1.5 text-2xs text-content-tertiary">
              <span className="truncate font-mono">{pack.slug}</span>
              <span className="text-border">·</span>
              <span
                className="shrink-0 rounded-full px-1.5 py-0.5 font-mono font-semibold"
                style={{
                  color: pack.branding.primary_color,
                  backgroundColor: `${pack.branding.primary_color}14`,
                }}
              >
                v{pack.pack_version}
              </span>
            </div>
          </div>
        </div>

        {/* Region / currency badges */}
        <div className="mt-3 flex items-center gap-1.5 flex-wrap">
          {countryName && (
            <Badge variant="blue" size="sm">
              <Globe size={10} className="mr-0.5" />
              {countryName}
            </Badge>
          )}
          <Badge variant="neutral" size="sm">{pack.default_currency}</Badge>
          {pack.default_tax_template && (
            <Badge variant="neutral" size="sm">{pack.default_tax_template}</Badge>
          )}
        </div>

        {pack.description && (
          <p className="mt-2.5 text-xs text-content-secondary line-clamp-3 leading-relaxed">
            {pack.description}
          </p>
        )}

        {/* Reference standards.
            These come from the pack's documentation metadata (regulator_refs
            or the raw validation_rule_pack slugs) and are NOT proof that the
            engine enforces them - for most packs none of them map to a
            registered rule set. Label them as reference-only and point at the
            apply dialog, which lists the rule packs that genuinely run. */}
        {standards.length > 0 && (
          <div className="mt-3">
            <div className="flex items-center gap-1.5 mb-1.5">
              <ShieldCheck size={12} className="text-content-tertiary" style={{ color: accent }} />
              <span className="text-2xs font-semibold text-content-tertiary uppercase tracking-wider">
                {t('modules.partner_pack_standards', { defaultValue: 'Reference standards' })}
              </span>
            </div>
            <div className="flex items-center gap-1 flex-wrap">
              {standards.slice(0, 6).map((std) => (
                <Badge key={std} variant="neutral" size="sm">{std}</Badge>
              ))}
              {standards.length > 6 && (
                <Badge variant="neutral" size="sm">+{standards.length - 6}</Badge>
              )}
            </div>
            <p className="mt-1.5 text-2xs text-content-tertiary leading-snug">
              {t('modules.partner_pack_standards_note', {
                defaultValue:
                  'Listed for reference. Enforced validation rules are shown when you activate the pack.',
              })}
            </p>
          </div>
        )}

        {/* Links */}
        {(pack.partner_url || supportEmail) && (
          <div className="mt-3 flex items-center gap-3 text-2xs">
            {pack.partner_url && (
              <a
                href={pack.partner_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-medium hover:underline"
                style={{ color: accent }}
              >
                <ExternalLink size={12} />
                {t('modules.partner_pack_website', { defaultValue: 'Website' })}
              </a>
            )}
            {supportEmail && (
              <a
                href={`mailto:${supportEmail}`}
                className="inline-flex items-center gap-1 text-content-tertiary hover:text-content-secondary hover:underline"
              >
                <Mail size={12} />
                {supportEmail}
              </a>
            )}
          </div>
        )}

        {/* Activate / deactivate */}
        <div className="mt-4 flex items-center gap-2 border-t border-border-light pt-3">
          {isActive ? (
            activeSource === 'env' ? (
              <span className="inline-flex items-center gap-1.5 text-2xs text-content-tertiary">
                <Info size={12} />
                {t('modules.pack_active_via_env', {
                  defaultValue: 'Active via environment (OE_PARTNER_PACK)',
                })}
              </span>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                icon={<Power size={14} />}
                onClick={() => setDeactivateOpen(true)}
              >
                {t('modules.pack_deactivate', { defaultValue: 'Deactivate' })}
              </Button>
            )
          ) : (
            <Button
              variant="primary"
              size="sm"
              icon={<Power size={14} />}
              onClick={() => setApplyOpen(true)}
            >
              {t('modules.pack_activate', { defaultValue: 'Activate pack' })}
            </Button>
          )}
        </div>
      </div>

      <PartnerPackApplyDialog
        open={applyOpen}
        onClose={() => setApplyOpen(false)}
        slug={pack.slug}
        partnerName={pack.partner_name}
      />
      <PartnerPackDeactivateDialog
        open={deactivateOpen}
        onClose={() => setDeactivateOpen(false)}
        partnerName={pack.partner_name}
      />
    </Card>
  );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* ── Module Toggles Section (shared between profiles tab) ────────────── */
/* ══════════════════════════════════════════════════════════════════════════ */

interface ModuleTogglesSectionProps {
  isModuleEnabled: (key: string) => boolean;
  setModuleEnabled: (key: string, enabled: boolean) => void;
  canDisable: (key: string) => { allowed: boolean; blockedBy: string[] };
  getEnabledDependents: (key: string) => string[];
}

function ModuleTogglesSection({
  isModuleEnabled,
  setModuleEnabled,
  canDisable,
  getEnabledDependents,
}: ModuleTogglesSectionProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const grouped = getModulesByCategory();

  function handleToggle(key: string, name: string, currentlyEnabled: boolean) {
    if (currentlyEnabled) {
      const { allowed, blockedBy } = canDisable(key);
      if (!allowed) {
        addToast({
          type: 'warning',
          title: t('modules.cannot_disable', { defaultValue: 'Cannot disable' }),
          message: t('modules.required_by', {
            defaultValue: '{{name}} is required by: {{deps}}',
            name,
            deps: blockedBy.join(', '),
          }),
        });
        return;
      }
    }
    setModuleEnabled(key, !currentlyEnabled);
    addToast({
      type: 'success',
      title: !currentlyEnabled
        ? t('modules.enabled', { defaultValue: '{{name}} enabled', name })
        : t('modules.disabled', { defaultValue: '{{name}} disabled', name }),
    });
  }

  const isI18nKey = (s: string) =>
    s.startsWith('modules.') ||
    s.startsWith('nav.') ||
    s.startsWith('validation.') ||
    s.startsWith('schedule.') ||
    s.startsWith('tendering.');

  const totalActive = MODULE_CATEGORY_ORDER.reduce((sum, cat) => {
    const mods = grouped[cat];
    return sum + (mods?.filter((m) => isModuleEnabled(m.id)).length ?? 0);
  }, 0);

  const totalMods = MODULE_CATEGORY_ORDER.reduce((sum, cat) => {
    return sum + (grouped[cat]?.length ?? 0);
  }, 0);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-content-secondary uppercase tracking-wider mb-0.5">
            {t('modules.active_modules', { defaultValue: 'Active Modules' })} ({totalActive})
          </h2>
          <p className="text-xs text-content-tertiary">
            {t('modules.section_desc', {
              defaultValue: 'Toggle optional features on or off. Disabled modules are hidden from the sidebar.',
            })}
          </p>
        </div>
        <span className="text-xs text-content-quaternary">
          {totalActive}/{totalMods}
        </span>
      </div>

      <div className="space-y-6">
        {MODULE_CATEGORY_ORDER.map((cat) => {
          const mods = grouped[cat];
          if (!mods || mods.length === 0) return null;
          const catMeta = MODULE_CATEGORY_META[cat] ?? { labelKey: cat, defaultLabel: cat };

          return (
            <div key={cat}>
              <div className="flex items-center gap-2 mb-2.5">
                <h3 className="text-xs font-semibold text-content-primary">
                  {t(catMeta.labelKey, { defaultValue: catMeta.defaultLabel })}
                </h3>
                <div className="flex-1 h-px bg-border-light" />
                <span className="text-2xs text-content-quaternary">
                  {mods.filter((m) => isModuleEnabled(m.id)).length}/{mods.length}{' '}
                  {t('modules.active_count', { defaultValue: 'active' })}
                </span>
              </div>

              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {mods.map((mod) => {
                  const Icon = mod.icon;
                  const enabled = isModuleEnabled(mod.id);
                  const deps = mod.depends ?? [];
                  const dependents = getEnabledDependents(mod.id);
                  const displayName = isI18nKey(mod.name)
                    ? t(mod.name, { defaultValue: formatModuleId(mod.id) })
                    : mod.name;
                  const displayDesc = isI18nKey(mod.description)
                    ? t(mod.description, { defaultValue: '' })
                    : mod.description;

                  return (
                    <ModuleToggleCard
                      key={mod.id}
                      icon={Icon}
                      name={displayName}
                      description={displayDesc}
                      version={mod.version}
                      enabled={enabled}
                      onToggle={() => handleToggle(mod.id, displayName, enabled)}
                      deps={deps}
                      dependents={dependents}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* ── Tab 2: Data Packages ────────────────────────────────────────────── */
/* ══════════════════════════════════════════════════════════════════════════ */

function DataPackagesTab() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [activeCategory, setActiveCategory] = useState<CategoryKey>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [marketplaceLimit, setMarketplaceLimit] = useState(12);
  const [installingId, setInstallingId] = useState<string | null>(null);

  const { data: modules, isLoading, isError: marketplaceError, refetch: refetchMarketplace } = useQuery({
    queryKey: ['marketplace'],
    queryFn: () => apiGet<MarketplaceModule[]>('/marketplace'),
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
  });

  const { data: demoStatus } = useQuery({
    queryKey: ['demo-status'],
    queryFn: () => apiGet<Record<string, boolean>>('/demo/status'),
  });

  const filtered = useMemo(() => {
    if (!modules) return [];
    const query = searchQuery.toLowerCase().trim();
    return modules.filter((mod) => {
      const matchesCategory = activeCategory === 'all' || mod.category === activeCategory;
      const matchesSearch =
        !query ||
        mod.name.toLowerCase().includes(query) ||
        mod.description.toLowerCase().includes(query) ||
        mod.tags.some((tag) => tag.toLowerCase().includes(query)) ||
        mod.author.toLowerCase().includes(query);
      return matchesCategory && matchesSearch;
    });
  }, [modules, activeCategory, searchQuery]);

  const categoryCounts = useMemo(() => {
    if (!modules) return {} as Record<CategoryKey, number>;
    const counts: Record<string, number> = { all: modules.length };
    for (const mod of modules) {
      counts[mod.category] = (counts[mod.category] ?? 0) + 1;
    }
    return counts as Record<CategoryKey, number>;
  }, [modules]);

  const CATALOG_ID_TO_REGION: Record<string, string> = {
    'catalog-ar-dubai': 'AR_DUBAI',
    'catalog-de-berlin': 'DE_BERLIN',
    'catalog-en-toronto': 'ENG_TORONTO',
    'catalog-sp-barcelona': 'SP_BARCELONA',
    'catalog-fr-paris': 'FR_PARIS',
    'catalog-hi-mumbai': 'HI_MUMBAI',
    'catalog-pt-saopaulo': 'PT_SAOPAULO',
    'catalog-ru-stpetersburg': 'RU_STPETERSBURG',
    'catalog-uk-gbp': 'UK_GBP',
    'catalog-usa-usd': 'USA_USD',
    'catalog-zh-shanghai': 'ZH_SHANGHAI',
  };

  async function handleInstallClick(mod: MarketplaceModule): Promise<void> {
    switch (mod.category) {
      case 'resource_catalog': {
        const region = CATALOG_ID_TO_REGION[mod.id];
        if (!region) {
          addToast({ type: 'error', title: t('marketplace.unknown_region', { defaultValue: 'Unknown region' }), message: t('marketplace.no_region_mapping', { defaultValue: 'No region mapping for {{id}}', id: mod.id }) });
          break;
        }
        setInstallingId(mod.id);
        try {
          const result = await apiPost<{ imported: number; skipped: number; region: string }>(`/v1/catalog/import/${region}`);
          addToast({
            type: 'success',
            title: t('marketplace.catalog_imported', { defaultValue: 'Catalog imported' }),
            message: t('marketplace.catalog_imported_message', { defaultValue: '{{imported}} resources imported, {{skipped}} skipped for {{region}}.', imported: result.imported, skipped: result.skipped, region: result.region }),
          });
          queryClient.invalidateQueries({ queryKey: ['marketplace'] });
          queryClient.invalidateQueries({ queryKey: ['catalog'] });
        } catch (err) {
          addToast({ type: 'error', title: t('marketplace.import_failed', { defaultValue: 'Import failed' }), message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }) });
        } finally {
          setInstallingId(null);
        }
        break;
      }
      case 'cost_database':
        navigate('/costs/import');
        break;
      case 'vector_index': {
        const VECTOR_ID_TO_DB: Record<string, string> = {
          'vector-usa-usd': 'USA_USD', 'vector-uk-gbp': 'UK_GBP',
          'vector-de-berlin': 'DE_BERLIN', 'vector-eng-toronto': 'ENG_TORONTO',
          'vector-fr-paris': 'FR_PARIS', 'vector-sp-barcelona': 'SP_BARCELONA',
          'vector-pt-saopaulo': 'PT_SAOPAULO', 'vector-ru-stpetersburg': 'RU_STPETERSBURG',
          'vector-ar-dubai': 'AR_DUBAI', 'vector-zh-shanghai': 'ZH_SHANGHAI',
          'vector-hi-mumbai': 'HI_MUMBAI',
        };
        const dbId = VECTOR_ID_TO_DB[mod.id];
        if (!dbId) {
          addToast({ type: 'error', title: t('marketplace.unknown_region', { defaultValue: 'Unknown region' }), message: t('marketplace.no_region_mapping', { defaultValue: 'No region mapping for {{id}}', id: mod.id }) });
          break;
        }
        setInstallingId(mod.id);

        // Probe embedder load state. If the model isn't resident yet,
        // surface a "Downloading model from HuggingFace..." hint so the
        // user understands why the install spinner is sitting on a
        // multi-hundred-MB cold start. Polled in parallel with the
        // install request; gives up after 60 s or once the install
        // request completes.
        let downloadPollAlive = true;
        let downloadHintShown = false;
        void (async () => {
          const pollStart = Date.now();
          while (downloadPollAlive && Date.now() - pollStart < 60_000) {
            try {
              const ds = await apiGet<{ model: string; status: string; dimension: number }>(
                '/v1/costs/vector/download-status/',
              );
              if (ds.status === 'ready') break;
              if (!downloadHintShown) {
                downloadHintShown = true;
                addToast({
                  type: 'info',
                  title: t('marketplace.embedder_downloading', {
                    defaultValue: 'Downloading model from HuggingFace…',
                  }),
                  message: t('marketplace.embedder_downloading_hint', {
                    defaultValue:
                      'First install pulls the embedding model ({{model}}). This can take a minute on slow connections.',
                    model: ds.model,
                  }),
                });
              }
            } catch {
              // Endpoint not reachable yet — skip this tick, keep polling.
            }
            await new Promise((resolve) => setTimeout(resolve, 1500));
          }
        })();

        try {
          const status = await apiGet<{ backend: string; connected: boolean; can_restore_snapshots: boolean; can_generate_locally: boolean }>('/v1/costs/vector/status/');
          let vecRes: { restored?: boolean; indexed?: number; database?: string; duration_seconds?: number } | undefined;
          if (status.can_restore_snapshots) {
            vecRes = await apiPost<{ restored?: boolean; indexed?: number; database?: string; duration_seconds?: number }>(`/v1/costs/vector/restore-snapshot/${dbId}`);
          } else if (status.connected) {
            vecRes = await apiPost<{ restored?: boolean; indexed?: number; database?: string; duration_seconds?: number }>(`/v1/costs/vector/load-github/${dbId}`);
          } else {
            throw new Error(t('marketplace.no_vector_backend', { defaultValue: 'No vector database available. Install LanceDB (pip install lancedb) or start Qdrant (docker run -p 6333:6333 qdrant/qdrant)' }));
          }
          // The POST can return ``indexed: 0`` when the backend is reachable but
          // could not actually build the index (no embedding model, or an empty
          // snapshot). Reflect that truthfully instead of always claiming success.
          const vecIndexed = vecRes?.indexed ?? 0;
          if (vecIndexed > 0) {
            addToast({
              type: 'success',
              title: t('marketplace.vector_imported', { defaultValue: 'Vector index loaded' }),
              message: t('marketplace.vector_ready_count', {
                defaultValue: '{{count}} vectors ready for {{region}}',
                count: vecIndexed,
                region: dbId,
              }),
            });
          } else {
            addToast({
              type: 'info',
              title: t('marketplace.vector_no_index', { defaultValue: 'No vectors indexed' }),
              message: t('marketplace.vector_no_index_message', {
                defaultValue:
                  'The vector backend is reachable but indexed 0 vectors for {{region}}. The embedding model is likely unavailable here, so semantic cost search stays limited until vectors are generated.',
                region: dbId,
              }),
            });
          }
          queryClient.invalidateQueries({ queryKey: ['marketplace'] });
          queryClient.invalidateQueries({ queryKey: ['vector-status'] });
        } catch (err) {
          addToast({ type: 'error', title: t('marketplace.import_failed', { defaultValue: 'Import failed' }), message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }) });
        } finally {
          downloadPollAlive = false;
          setInstallingId(null);
        }
        break;
      }
      case 'demo_project': {
        const demoId = mod.id.replace('demo-', '');
        setInstallingId(mod.id);
        try {
          const result = await apiPost<{ project_id: string; project_name: string; already_installed?: boolean }>(`/demo/install/${demoId}`);
          if (result.already_installed) {
            addToast({
              type: 'info',
              title: t('marketplace.demo_already_installed', { defaultValue: 'Already installed' }),
              message: t('marketplace.demo_already_installed_message', {
                defaultValue: '{{name}} is already installed. Opening existing project.',
                name: result.project_name,
              }),
            });
          } else {
            addToast({ type: 'success', title: t('marketplace.demo_installed', { defaultValue: 'Demo installed' }), message: t('marketplace.demo_installed_message', { defaultValue: '{{name}} created with full BOQ, schedule, budget, and tendering.', name: result.project_name }) });
          }
          queryClient.invalidateQueries({ queryKey: ['demo-status'] });
          queryClient.invalidateQueries({ queryKey: ['marketplace'] });
          queryClient.invalidateQueries({ queryKey: ['projects'] });
          navigate(`/projects/${result.project_id}`);
        } catch (err) {
          addToast({ type: 'error', title: t('marketplace.install_failed', { defaultValue: 'Install failed' }), message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }) });
        } finally {
          setInstallingId(null);
        }
        break;
      }
      case 'integration':
        navigate('/settings');
        break;
    }
  }

  async function handleUninstallDemo(demoId: string): Promise<void> {
    const confirmed = await confirm({
      title: t('marketplace.uninstall_demo_confirm_title', { defaultValue: 'Uninstall demo?' }),
      message: t('marketplace.uninstall_demo_confirm', {
        defaultValue: 'Are you sure you want to uninstall this demo project? All associated data will be deleted.',
      }),
    });
    if (!confirmed) return;
    setInstallingId(`demo-${demoId}`);
    try {
      const result = await apiDelete<{ deleted_projects: number }>(`/demo/uninstall/${demoId}`);
      addToast({
        type: 'success',
        title: t('marketplace.demo_uninstalled', { defaultValue: 'Demo uninstalled' }),
        message: t('marketplace.demo_uninstalled_message', { defaultValue: '{{count}} project(s) removed.', count: result.deleted_projects }),
      });
      queryClient.invalidateQueries({ queryKey: ['demo-status'] });
      queryClient.invalidateQueries({ queryKey: ['marketplace'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('marketplace.uninstall_failed', { defaultValue: 'Uninstall failed' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setInstallingId(null);
    }
  }

  async function handleReinstallDemo(demoId: string): Promise<void> {
    const confirmed = await confirm({
      title: t('marketplace.reinstall_demo_confirm_title', { defaultValue: 'Reinstall demo?' }),
      message: t('marketplace.reinstall_demo_confirm', {
        defaultValue: 'This will delete the existing demo project and create a fresh copy. All changes you made to the demo will be lost.',
      }),
    });
    if (!confirmed) return;
    setInstallingId(`demo-${demoId}`);
    try {
      const result = await apiPost<{ project_id: string; project_name: string }>(`/demo/install/${demoId}?force=true`);
      addToast({
        type: 'success',
        title: t('marketplace.demo_reinstalled', { defaultValue: 'Demo reinstalled' }),
        message: t('marketplace.demo_reinstalled_message', {
          defaultValue: '{{name}} has been recreated with fresh data.',
          name: result.project_name,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['demo-status'] });
      queryClient.invalidateQueries({ queryKey: ['marketplace'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate(`/projects/${result.project_id}`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('marketplace.reinstall_failed', { defaultValue: 'Reinstall failed' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setInstallingId(null);
    }
  }

  async function handleClearAllDemos(): Promise<void> {
    const confirmed = await confirm({
      title: t('marketplace.clear_all_demos_confirm_title', { defaultValue: 'Clear all demos?' }),
      message: t('marketplace.clear_all_demos_confirm', {
        defaultValue: 'Are you sure you want to remove ALL demo projects and their data? This cannot be undone.',
      }),
    });
    if (!confirmed) return;
    try {
      const result = await apiDelete<{ deleted_projects: number }>('/demo/clear-all');
      addToast({
        type: 'success',
        title: t('marketplace.demos_cleared', { defaultValue: 'Demo data cleared' }),
        message: t('marketplace.demos_cleared_message', { defaultValue: '{{count}} demo project(s) removed.', count: result.deleted_projects }),
      });
      queryClient.invalidateQueries({ queryKey: ['demo-status'] });
      queryClient.invalidateQueries({ queryKey: ['marketplace'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('marketplace.clear_failed', { defaultValue: 'Clear failed' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    }
  }

  return (
    <div className="animate-card-in" style={{ animationDelay: '60ms' }}>
      {/* Installed packages summary */}
      {modules && modules.filter((m) => m.installed).length > 0 && (
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-content-tertiary uppercase tracking-wider">
              {t('marketplace.my_modules', { defaultValue: 'Installed Packages' })}
            </h3>
            {demoStatus && Object.values(demoStatus).some(Boolean) && (
              <Button variant="ghost" size="sm" icon={<Trash2 size={14} />} onClick={() => void handleClearAllDemos()}>
                {t('marketplace.clear_demo_data', { defaultValue: 'Clear All Demo Data' })}
              </Button>
            )}
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {modules.filter((m) => m.installed).map((mod) => {
              const Icon = getModuleIcon(mod.icon);
              const statusBadge = getInstalledModuleBadge(mod, t);
              return (
                <div
                  key={mod.id}
                  className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-elevated px-3 py-2.5 transition-all hover:border-border"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-semantic-success-bg text-semantic-success dark:text-emerald-400">
                    <Icon size={15} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <span className="text-xs font-medium text-content-primary truncate block">{mod.name}</span>
                    <span className="text-2xs text-content-tertiary">{statusBadge.subtitle}</span>
                  </div>
                  {statusBadge.type === 'badge' ? (
                    <Badge variant="success" size="sm"><Check size={10} className="mr-0.5" />{statusBadge.label}</Badge>
                  ) : statusBadge.type === 'manage' ? (
                    <Button variant="secondary" size="sm" onClick={() => navigate('/costs/import')}>
                      {t('marketplace.manage', 'Manage')}
                    </Button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Available packages header */}
      <h2 className="text-sm font-semibold text-content-secondary uppercase tracking-wider mb-3 mt-4">
        {t('marketplace.available', { defaultValue: 'Data Packages & Add-ons' })}
      </h2>

      {/* Search */}
      <div className="mb-6 max-w-md">
        <Input
          aria-label={t('marketplace.search_packages', { defaultValue: 'Search packages' })}
          placeholder={t('marketplace.search_placeholder', { defaultValue: 'Search packages...' })}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          icon={<Search size={16} />}
        />
      </div>

      {/* Category tabs */}
      <div className="mb-6 flex flex-wrap gap-2">
        {CATEGORY_KEYS.map((key) => {
          const meta = CATEGORIES[key];
          const Icon = meta.icon;
          const isActive = activeCategory === key;
          const count = categoryCounts[key] ?? 0;
          return (
            <button
              key={key}
              onClick={() => setActiveCategory(key)}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-fast ease-oe',
                isActive
                  ? 'bg-oe-blue text-content-inverse shadow-xs'
                  : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary hover:text-content-primary',
              )}
            >
              <Icon size={14} strokeWidth={1.75} />
              <span>{t(meta.labelKey, { defaultValue: meta.defaultLabel })}</span>
              {count > 0 && (
                <span
                  className={clsx(
                    'ml-0.5 text-2xs font-semibold rounded-full px-1.5',
                    isActive ? 'bg-white/20 text-content-inverse' : 'bg-surface-primary text-content-tertiary',
                  )}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Module grid */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="animate-pulse">
              <div className="flex items-start gap-3">
                <div className="h-11 w-11 rounded-xl bg-surface-secondary" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-2/3 rounded bg-surface-secondary" />
                  <div className="h-3 w-full rounded bg-surface-secondary" />
                  <div className="h-3 w-1/2 rounded bg-surface-secondary" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : marketplaceError ? (
        <div className="py-16 text-center">
          <AlertTriangle size={40} className="mx-auto mb-3 text-semantic-warning" strokeWidth={1.5} />
          <p className="text-sm font-medium text-content-secondary">
            {t('marketplace.load_failed', { defaultValue: 'Failed to load marketplace' })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('marketplace.load_failed_hint', {
              defaultValue: 'Check your connection and try again.',
            })}
          </p>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw size={14} />}
            onClick={() => void refetchMarketplace()}
            className="mt-4"
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-16 text-center">
          <Package size={40} className="mx-auto mb-3 text-content-tertiary" />
          <p className="text-sm font-medium text-content-secondary">
            {t('marketplace.no_results', { defaultValue: 'No modules found' })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('marketplace.no_results_hint', { defaultValue: 'Try adjusting your search or category filter.' })}
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.slice(0, marketplaceLimit).map((mod, i) => {
              const isDemoInstalled = mod.category === 'demo_project' && demoStatus?.[mod.id.replace('demo-', '')] === true;
              return (
                <MarketplaceCard
                  key={mod.id}
                  module={mod}
                  index={i}
                  isInstalling={installingId === mod.id}
                  onInstall={() => void handleInstallClick(mod)}
                  isDemoInstalled={isDemoInstalled}
                  onUninstallDemo={
                    mod.category === 'demo_project'
                      ? () => void handleUninstallDemo(mod.id.replace('demo-', ''))
                      : undefined
                  }
                  onReinstallDemo={
                    mod.category === 'demo_project'
                      ? () => void handleReinstallDemo(mod.id.replace('demo-', ''))
                      : undefined
                  }
                />
              );
            })}
          </div>
          {filtered.length > marketplaceLimit && (
            <div className="mt-6 text-center">
              <Button variant="secondary" onClick={() => setMarketplaceLimit((prev) => prev + 12)}>
                {t('marketplace.show_more', {
                  defaultValue: 'Show more ({{remaining}} remaining)',
                  remaining: filtered.length - marketplaceLimit,
                })}
              </Button>
            </div>
          )}
        </>
      )}

      {/* Community / Build Your Own */}
      <div className="mt-12">
        <Card>
          <div className="relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-purple-500/[0.05] via-indigo-500/[0.03] to-blue-500/[0.05]" />
            <div className="relative p-6">
              <div className="flex items-center gap-2 mb-3">
                <Plug size={20} className="text-purple-500" />
                <h2 className="text-lg font-semibold text-content-primary">
                  {t('modules.community_title', { defaultValue: 'Build Your Own Module' })}
                </h2>
              </div>
              <p className="text-sm text-content-secondary leading-relaxed mb-4">
                {t('modules.community_desc', { defaultValue: 'OpenConstructionERP has a modular plugin architecture. Anyone can create custom modules - cost databases, regional standards, CAD converters, analytics dashboards, integrations with external systems, or any other functionality.' })}
              </p>
              <div className="flex flex-wrap gap-3">
                <a
                  href="mailto:info@datadrivenconstruction.io?subject=OpenConstructionERP%20Module%20Proposal"
                  className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 transition-colors"
                >
                  <Package size={16} />
                  {t('modules.community_submit_email', { defaultValue: 'Submit Module via Email' })}
                </a>
                <a
                  href="https://github.com/datadrivenconstruction/OpenConstructionERP/issues/new?title=Module%20Proposal:%20&labels=module-proposal"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-4 py-2 text-sm font-medium text-content-primary hover:bg-surface-secondary/80 transition-colors"
                >
                  <Info size={16} />
                  {t('modules.community_submit_github', { defaultValue: 'Propose on GitHub' })}
                </a>
                <a
                  href="https://t.me/datadrivenconstruction"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-4 py-2 text-sm font-medium text-content-primary hover:bg-surface-secondary/80 transition-colors"
                >
                  <Globe size={16} />
                  {t('modules.community_telegram', { defaultValue: 'Discuss in Telegram' })}
                </a>
              </div>
            </div>
          </div>
        </Card>
      </div>
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* ── Tab 3: System Modules ───────────────────────────────────────────── */
/* ══════════════════════════════════════════════════════════════════════════ */

function SystemModulesTab() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const userRole = useAuthStore((s) => s.userRole);
  const isAdmin = userRole === 'admin';
  const [togglingModule, setTogglingModule] = useState<string | null>(null);

  const { data: systemModules, refetch, isLoading, isError: systemError } = useQuery({
    queryKey: ['system-modules'],
    queryFn: () => apiGet<SystemModule[]>('/v1/modules/'),
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
  });

  const enabledCount = systemModules?.filter((m) => m.enabled).length ?? 0;

  async function handleBackendToggle(mod: SystemModule): Promise<void> {
    // Enabling/disabling a backend module is admin-only on the server
    // (RequirePermission("admin")). Guard here so non-admins never fire a
    // request that 403s — the toggle is also disabled in the UI for them.
    if (!isAdmin) {
      addToast({
        type: 'warning',
        title: t('modules.admin_only', { defaultValue: 'Admin only' }),
        message: t('modules.admin_only_modules', {
          defaultValue: 'Only administrators can enable or disable system modules.',
        }),
      });
      return;
    }
    if (mod.is_core) {
      addToast({
        type: 'warning',
        title: t('modules.cannot_disable', { defaultValue: 'Cannot disable' }),
        message: t('modules.core_module_locked', {
          defaultValue: '{{name}} is a core module and cannot be disabled.',
          name: mod.display_name,
        }),
      });
      return;
    }
    setTogglingModule(mod.name);
    const action = mod.enabled ? 'disable' : 'enable';
    try {
      await apiPost<{ name: string; status: string }>(`/v1/modules/${mod.name}/${action}`);
      addToast({
        type: 'success',
        title: action === 'enable'
          ? t('modules.enabled', { defaultValue: '{{name}} enabled', name: mod.display_name })
          : t('modules.disabled', { defaultValue: '{{name}} disabled', name: mod.display_name }),
      });
      // Invalidate the shared ['system-modules'] query so BOTH this tab and
      // the Sidebar (which reads the same key to gate routes for disabled
      // backend modules) refetch and stay in sync — without this, disabling
      // a module left its sidebar route live and broken.
      void queryClient.invalidateQueries({ queryKey: ['system-modules'] });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('modules.toggle_failed', { defaultValue: 'Toggle failed' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setTogglingModule(null);
    }
  }

  if (systemError) {
    return (
      <div className="py-16 text-center animate-card-in">
        <AlertTriangle size={40} className="mx-auto mb-3 text-semantic-warning" strokeWidth={1.5} />
        <p className="text-sm font-medium text-content-secondary">
          {t('modules.system_load_failed', { defaultValue: 'Failed to load system modules' })}
        </p>
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw size={14} />}
          onClick={() => void refetch()}
          className="mt-4"
        >
          {t('common.retry', { defaultValue: 'Retry' })}
        </Button>
      </div>
    );
  }

  // Loading skeleton — keeps the empty-state ("No system modules loaded")
  // from flashing during the initial fetch.
  if (isLoading) {
    return (
      <div className="animate-card-in" style={{ animationDelay: '60ms' }}>
        <div className="mb-4 space-y-1.5">
          <div className="h-4 w-32 rounded bg-surface-secondary animate-pulse" />
          <div className="h-3 w-2/3 rounded bg-surface-secondary animate-pulse" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <Card key={i} className="animate-pulse" padding="sm">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 shrink-0 rounded-lg bg-surface-secondary" />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="h-3 w-2/3 rounded bg-surface-secondary" />
                  <div className="h-2.5 w-1/3 rounded bg-surface-secondary" />
                </div>
                <div className="h-5 w-9 shrink-0 rounded-full bg-surface-secondary" />
              </div>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (!systemModules || systemModules.length === 0) {
    return (
      <div className="py-16 text-center animate-card-in">
        <Server size={40} className="mx-auto mb-3 text-content-tertiary" />
        <p className="text-sm font-medium text-content-secondary">
          {t('modules.no_system_modules', { defaultValue: 'No system modules loaded' })}
        </p>
      </div>
    );
  }

  return (
    <div className="animate-card-in" style={{ animationDelay: '60ms' }}>
      <div className="mb-4">
        <p className="text-sm text-content-secondary">
          {enabledCount}/{systemModules.length}{' '}
          {t('marketplace.modules_enabled', { defaultValue: 'modules enabled' })}
        </p>
        <InfoHint
          inline
          className="mt-1"
          text={t('modules.system_hint', {
            defaultValue: 'System modules are backend plugins loaded from the server. Toggle non-core modules to enable or disable them.',
          })}
        />
        {!isAdmin && (
          <p className="mt-1.5 inline-flex items-center gap-1.5 text-2xs text-content-tertiary">
            <ShieldCheck size={12} className="shrink-0" />
            {t('modules.system_admin_only_hint', {
              defaultValue: 'Only administrators can enable or disable system modules.',
            })}
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {systemModules.map((mod, i) => (
          <Card
            key={mod.name}
            className="animate-card-in"
            style={{ animationDelay: `${80 + i * 30}ms` }}
            padding="sm"
          >
            <div className="flex items-center gap-2.5">
              <div
                className={clsx(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors',
                  mod.enabled
                    ? 'bg-semantic-success-bg text-semantic-success dark:text-emerald-400'
                    : 'bg-surface-tertiary text-content-quaternary',
                )}
              >
                {mod.is_core ? <ShieldCheck size={15} /> : <Package size={15} />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-semibold text-content-primary truncate">
                    {mod.display_name}
                  </span>
                  {mod.is_core ? (
                    <Badge variant="blue" size="sm">{t('modules.core', { defaultValue: 'Core' })}</Badge>
                  ) : mod.enabled ? (
                    <Badge variant="success" size="sm" dot>{t('marketplace.active', { defaultValue: 'Active' })}</Badge>
                  ) : (
                    <Badge variant="neutral" size="sm">{t('modules.disabled_label', { defaultValue: 'Disabled' })}</Badge>
                  )}
                </div>
                <div className="flex items-center gap-1.5 text-2xs text-content-tertiary">
                  <span className="font-mono">v{mod.version}</span>
                  {mod.category && mod.category !== 'core' && (
                    <>
                      <span className="text-border">|</span>
                      <span>{mod.category}</span>
                    </>
                  )}
                </div>
                {mod.description && (
                  <p className="text-2xs text-content-quaternary mt-0.5 line-clamp-1">{mod.description}</p>
                )}
                {mod.depends && mod.depends.length > 0 && (
                  <span className="text-2xs text-content-quaternary">
                    {t('modules.depends_on', { defaultValue: 'Requires: {{deps}}', deps: mod.depends.join(', ') })}
                  </span>
                )}
              </div>

              {!mod.is_core && (
                <button
                  onClick={() => void handleBackendToggle(mod)}
                  disabled={togglingModule === mod.name || !isAdmin}
                  role="switch"
                  aria-checked={mod.enabled}
                  title={
                    isAdmin
                      ? undefined
                      : t('modules.admin_only', { defaultValue: 'Admin only' })
                  }
                  aria-label={
                    isAdmin
                      ? t('modules.toggle_module', {
                          defaultValue: '{{action}} {{name}}',
                          action: mod.enabled ? t('common.disable', { defaultValue: 'Disable' }) : t('common.enable', { defaultValue: 'Enable' }),
                          name: mod.display_name,
                        })
                      : t('modules.toggle_module_admin_only', {
                          defaultValue: '{{name}} - admin only',
                          name: mod.display_name,
                        })
                  }
                  className={clsx('shrink-0', !isAdmin && 'cursor-not-allowed opacity-50')}
                >
                  {togglingModule === mod.name ? (
                    <Loader2 size={16} className="animate-spin text-content-tertiary" />
                  ) : (
                    <div
                      className={clsx(
                        'relative h-5 w-9 rounded-full transition-colors duration-200',
                        mod.enabled ? 'bg-oe-blue' : 'bg-content-quaternary/40',
                      )}
                    >
                      <div
                        className={clsx(
                          'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200',
                          mod.enabled ? 'translate-x-[18px]' : 'translate-x-0.5',
                        )}
                      />
                    </div>
                  )}
                </button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════ */
/* ── Shared sub-components ───────────────────────────────────────────── */
/* ══════════════════════════════════════════════════════════════════════════ */

/* ── Module Toggle Card ────────────────────────────────────────────────── */

interface ModuleToggleCardProps {
  icon: LucideIcon;
  name: string;
  description: string;
  version?: string;
  enabled: boolean;
  onToggle: () => void;
  deps?: string[];
  dependents?: string[];
}

function ModuleToggleCard({
  icon: Icon,
  name,
  description,
  version,
  enabled,
  onToggle,
  deps,
  dependents,
}: ModuleToggleCardProps) {
  const { t } = useTranslation();
  const hasBlockers = (dependents ?? []).length > 0;

  return (
    <div
      className={clsx(
        'flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-all',
        enabled
          ? 'border-border-light bg-surface-elevated hover:border-border'
          : 'border-border-light/50 bg-surface-secondary/50 opacity-60 hover:opacity-80',
      )}
    >
      <div
        className={clsx(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors',
          enabled ? 'bg-oe-blue-subtle text-oe-blue-text' : 'bg-surface-tertiary text-content-quaternary',
        )}
      >
        <Icon size={15} />
      </div>
      <div className="min-w-0 flex-1">
        <span className="text-xs font-medium text-content-primary truncate block">{name}</span>
        <span className="text-2xs text-content-tertiary line-clamp-1">
          {description}
          {version ? ` · v${version}` : ''}
        </span>
        {hasBlockers && enabled && (
          <div className="flex items-center gap-1 mt-0.5">
            <AlertTriangle size={9} className="text-amber-500 shrink-0" />
            <span className="text-2xs text-amber-600 dark:text-amber-400 truncate">
              {t('modules.required_by_short', {
                defaultValue: 'Required by {{deps}}',
                deps: (dependents ?? []).join(', '),
              })}
            </span>
          </div>
        )}
        {deps && deps.length > 0 && (
          <span className="text-2xs text-content-quaternary">
            {t('modules.depends_on', { defaultValue: 'Requires: {{deps}}', deps: deps.join(', ') })}
          </span>
        )}
      </div>

      <button
        onClick={onToggle}
        role="switch"
        aria-checked={enabled}
        aria-label={t('modules.toggle_module', {
          defaultValue: '{{action}} {{name}}',
          action: enabled ? t('common.disable', { defaultValue: 'Disable' }) : t('common.enable', { defaultValue: 'Enable' }),
          name,
        })}
        className="shrink-0"
      >
        <div
          className={clsx(
            'relative h-5 w-9 rounded-full transition-colors duration-200',
            enabled ? 'bg-oe-blue' : 'bg-content-quaternary/40',
          )}
        >
          <div
            className={clsx(
              'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200',
              enabled ? 'translate-x-[18px]' : 'translate-x-0.5',
            )}
          />
        </div>
      </button>
    </div>
  );
}

/* ── Marketplace Card ──────────────────────────────────────────────────── */

interface MarketplaceCardProps {
  module: MarketplaceModule;
  index: number;
  isInstalling?: boolean;
  onInstall: () => void;
  isDemoInstalled?: boolean;
  onUninstallDemo?: () => void;
  onReinstallDemo?: () => void;
}

function MarketplaceCard({ module: mod, index, isInstalling, onInstall, isDemoInstalled, onUninstallDemo, onReinstallDemo }: MarketplaceCardProps) {
  const { t } = useTranslation();
  const Icon = getModuleIcon(mod.icon);
  const isLanguage = mod.category === 'language';
  const isBuiltIn = mod.category === 'converter' || mod.category === 'analytics';
  const isIntegration = mod.category === 'integration';

  return (
    <Card hoverable className="animate-card-in group" style={{ animationDelay: `${80 + index * 30}ms` }}>
      <div className="flex items-start gap-3">
        <div
          className={clsx(
            'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-colors duration-fast ease-oe',
            mod.category === 'resource_catalog'
              ? 'bg-semantic-warning-bg text-semantic-warning'
              : mod.category === 'cost_database'
                ? 'bg-oe-blue-subtle text-oe-blue-text'
                : mod.category === 'vector_index'
                  ? 'bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400'
                  : mod.category === 'language'
                    ? 'bg-semantic-success-bg text-semantic-success dark:text-emerald-400'
                    : mod.category === 'converter'
                      ? 'bg-semantic-warning-bg text-semantic-warning'
                      : mod.category === 'analytics'
                        ? 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400'
                        : 'bg-surface-secondary text-content-secondary',
          )}
        >
          <Icon size={20} strokeWidth={1.75} />
        </div>

        <div className="min-w-0 flex-1">
          <span className="text-sm font-semibold text-content-primary truncate block">{mod.name}</span>
          <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-content-tertiary">
            <span>{mod.author}</span>
            <span className="text-border">|</span>
            <span className="font-mono">v{mod.version}</span>
            <span className="text-border">|</span>
            <span>{formatSize(mod.size_mb)}</span>
          </div>
          <p className="mt-2 text-xs text-content-secondary line-clamp-2 leading-relaxed">{mod.description}</p>

          {/* Vector index hint */}
          {mod.category === 'vector_index' && !mod.installed && (
            <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-purple-50 dark:bg-purple-900/20 border border-purple-200/50 dark:border-purple-800/30 px-2.5 py-1.5">
              <Info size={12} className="text-purple-500 shrink-0 mt-0.5" />
              <div className="text-2xs text-purple-700 dark:text-purple-300 leading-relaxed">
                <strong>{t('marketplace.vector_option_a', { defaultValue: 'Option A' })}:</strong> Qdrant + Snapshot (3072d):<br />
                <code className="font-mono bg-purple-100 dark:bg-purple-800/40 px-1 rounded text-[10px]">docker run -p 6333:6333 qdrant/qdrant</code><br />
                <strong>{t('marketplace.vector_option_b', { defaultValue: 'Option B' })}:</strong> LanceDB (384d):<br />
                <code className="font-mono bg-purple-100 dark:bg-purple-800/40 px-1 rounded text-[10px]">pip install lancedb sentence-transformers</code>
              </div>
            </div>
          )}

          {/* Tags */}
          <div className="mt-3 flex items-center gap-1.5 flex-wrap">
            {mod.tags.slice(0, 3).map((tag) => (
              <Badge key={tag} variant="neutral" size="sm">{tag}</Badge>
            ))}
            {mod.tags.length > 3 && <Badge variant="neutral" size="sm">+{mod.tags.length - 3}</Badge>}
            <div className="flex-1" />
            {!isLanguage && <Badge variant="success" size="sm">{t('marketplace.free', { defaultValue: 'Free' })}</Badge>}
          </div>

          {/* Action button */}
          <div className="mt-3">
            {isLanguage ? (
              <Badge variant="success" size="sm"><Check size={10} className="mr-0.5" />{t('marketplace.included', { defaultValue: 'Included' })}</Badge>
            ) : isBuiltIn ? (
              <Badge variant="success" size="sm"><Check size={10} className="mr-0.5" />{t('marketplace.builtin', { defaultValue: 'Built-in' })}</Badge>
            ) : isIntegration ? (
              <Button variant="secondary" size="sm" icon={<Settings size={14} />} onClick={onInstall}>
                {t('marketplace.requires_setup', { defaultValue: 'Configure' })}
              </Button>
            ) : mod.installed && mod.category === 'cost_database' ? (
              <Button variant="secondary" size="sm" icon={<Check size={14} />} onClick={onInstall}>
                {t('marketplace.manage', { defaultValue: 'Manage' })}
              </Button>
            ) : mod.installed && mod.category === 'resource_catalog' ? (
              <Button variant="secondary" size="sm" disabled icon={<Check size={14} />}>
                {t('marketplace.imported', { defaultValue: 'Imported' })}
              </Button>
            ) : mod.installed && mod.category === 'vector_index' ? (
              <Button variant="secondary" size="sm" disabled icon={<Check size={14} />}>
                {t('marketplace.indexed', { defaultValue: 'Indexed' })}
              </Button>
            ) : (mod.installed || isDemoInstalled) && mod.category === 'demo_project' ? (
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="success" size="sm"><Check size={10} className="mr-0.5" />{t('marketplace.installed', { defaultValue: 'Installed' })}</Badge>
                {onReinstallDemo && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={isInstalling ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                    onClick={onReinstallDemo}
                    disabled={isInstalling}
                    className="text-content-secondary hover:text-content-primary hover:bg-surface-secondary"
                  >
                    {t('marketplace.reinstall', { defaultValue: 'Reinstall' })}
                  </Button>
                )}
                {onUninstallDemo && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={isInstalling ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    onClick={onUninstallDemo}
                    disabled={isInstalling}
                    className="text-red-600 hover:text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:text-red-300 dark:hover:bg-red-900/20"
                  >
                    {t('marketplace.uninstall', { defaultValue: 'Uninstall' })}
                  </Button>
                )}
              </div>
            ) : (
              <Button
                variant="primary"
                size="sm"
                icon={isInstalling ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                onClick={onInstall}
                disabled={isInstalling}
              >
                {isInstalling
                  ? t('marketplace.installing', { defaultValue: 'Installing...' })
                  : t('marketplace.install', { defaultValue: 'Install' })}
              </Button>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

/* ── Installed module badge helper ──────────────────────────────────────── */

interface InstalledBadgeInfo {
  type: 'badge' | 'manage';
  label: string;
  subtitle: string;
}

function getInstalledModuleBadge(
  mod: MarketplaceModule,
  t: (key: string, opts?: Record<string, unknown>) => string,
): InstalledBadgeInfo {
  switch (mod.category) {
    case 'language':
      return { type: 'badge', label: t('marketplace.included', { defaultValue: 'Included' }), subtitle: t('marketplace.included', { defaultValue: 'Included' }) };
    case 'analytics':
    case 'converter':
      return { type: 'badge', label: t('marketplace.builtin', { defaultValue: 'Built-in' }), subtitle: t('marketplace.builtin', { defaultValue: 'Built-in' }) };
    case 'integration':
      return { type: 'manage', label: t('marketplace.configure', { defaultValue: 'Configure' }), subtitle: t('marketplace.requires_setup', { defaultValue: 'Requires Setup' }) };
    case 'resource_catalog':
      return { type: 'badge', label: t('marketplace.imported', { defaultValue: 'Imported' }), subtitle: t('marketplace.imported', { defaultValue: 'Imported' }) };
    case 'vector_index':
      return { type: 'badge', label: t('marketplace.indexed', { defaultValue: 'Indexed' }), subtitle: t('marketplace.indexed', { defaultValue: 'Indexed' }) };
    case 'demo_project':
      return { type: 'badge', label: t('marketplace.installed', { defaultValue: 'Installed' }), subtitle: t('marketplace.installed', { defaultValue: 'Installed' }) };
    case 'cost_database':
      return { type: 'manage', label: t('marketplace.manage', { defaultValue: 'Manage' }), subtitle: `v${mod.version}` };
    default:
      return { type: 'badge', label: t('marketplace.installed', { defaultValue: 'Installed' }), subtitle: `v${mod.version}` };
  }
}
