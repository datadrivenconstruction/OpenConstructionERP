// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ModulesSettings — install / remove backend modules from the Settings page.
 *
 * The platform has two separate "module is on" systems and they answer
 * different questions:
 *
 *   1. The backend module loader (`/v1/modules/`) decides whether a module's
 *      routes and models are mounted at all. That is installation, it is
 *      instance-wide, and it is admin-only. This panel drives that one.
 *   2. `useModuleStore` decides whether a nav entry shows in *your* sidebar.
 *      That is a personal view preference, it is per-user, and it is edited
 *      from the sidebar's "Edit menu" and from the onboarding wizard.
 *
 * Mixing them is what makes the feature confusing, so this panel says which
 * one it is in its intro copy and links to the other.
 *
 * Query key `['system-modules']` is shared with the Modules registry page and
 * with `Sidebar.tsx`, which hides routes whose backing module is disabled. A
 * successful toggle invalidates it once and all three surfaces re-read.
 */

import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Package,
  Search,
  ChevronDown,
  ChevronRight,
  Lock,
  AlertTriangle,
  ArrowUpRight,
  Loader2,
  Info,
} from 'lucide-react';
import clsx from 'clsx';
import { Card, CardHeader, CardContent, Badge, Button, ConfirmDialog } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { resolveModuleDisplayName } from '@/features/modules/moduleDisplayName';
import { fmtList } from '@/shared/lib/formatters';

/* ── Types ───────────────────────────────────────────────────────────────── */

/** One row of `GET /v1/modules/`. Mirrors `ModuleLoader.list_modules()`. */
export interface SettingsModule {
  name: string;
  version: string;
  display_name: string;
  display_name_i18n?: Record<string, string> | null;
  description: string;
  author: string;
  category: string;
  depends: string[];
  optional_depends: string[];
  has_router: boolean;
  loaded: boolean;
  enabled: boolean;
  is_core: boolean;
}

/* ── Category buckets ────────────────────────────────────────────────────── */

/**
 * Manifest `category` is free text and today carries twelve distinct values,
 * several of them one-offs (`infra`, `developer_tools`, `project_controls`).
 * Rendering the raw value would leak a snake_case English word into every
 * locale the moment someone writes a new manifest, so the known values map to
 * a closed key set and anything unrecognised falls into one "Other" bucket.
 */
const CATEGORY_KEYS: Record<string, string> = {
  business: 'settings.modules_cat_business',
  regional: 'settings.modules_cat_regional',
  extension: 'settings.modules_cat_extension',
  controls: 'settings.modules_cat_controls',
  project_controls: 'settings.modules_cat_controls',
  enterprise: 'settings.modules_cat_enterprise',
  integration: 'settings.modules_cat_integration',
  infra: 'settings.modules_cat_infra',
  estimation: 'settings.modules_cat_estimation',
  developer_tools: 'settings.modules_cat_developer',
  compliance: 'settings.modules_cat_compliance',
};

const CATEGORY_DEFAULTS: Record<string, string> = {
  'settings.modules_cat_business': 'Business & commercial',
  'settings.modules_cat_regional': 'Regional',
  'settings.modules_cat_extension': 'Extensions',
  'settings.modules_cat_controls': 'Project controls',
  'settings.modules_cat_enterprise': 'Enterprise',
  'settings.modules_cat_integration': 'Integrations',
  'settings.modules_cat_infra': 'Platform',
  'settings.modules_cat_estimation': 'Estimating',
  'settings.modules_cat_developer': 'Developer tools',
  'settings.modules_cat_compliance': 'Compliance',
  'settings.modules_cat_other': 'Other',
};

/** Bucket key for a manifest category, closed to the map above. */
function categoryKey(category: string): string {
  return CATEGORY_KEYS[category] ?? 'settings.modules_cat_other';
}

/* ── Toggle ──────────────────────────────────────────────────────────────── */

function ModuleToggle({
  enabled,
  disabled,
  busy,
  label,
  onToggle,
}: {
  enabled: boolean;
  disabled: boolean;
  busy: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={label}
      disabled={disabled || busy}
      onClick={onToggle}
      className={clsx(
        'relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
        enabled ? 'bg-oe-blue' : 'bg-gray-300 dark:bg-gray-600',
        disabled || busy ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
      )}
    >
      <span
        className={clsx(
          'pointer-events-none inline-flex h-5 w-5 transform items-center justify-center rounded-full bg-white shadow transition duration-200 ease-in-out',
          enabled ? 'translate-x-5' : 'translate-x-0',
        )}
      >
        {busy && <Loader2 size={11} className="animate-spin text-oe-blue" aria-hidden />}
      </span>
    </button>
  );
}

/* ── One module row ──────────────────────────────────────────────────────── */

/**
 * Declared at module scope on purpose. Nested inside the panel it would be a
 * fresh component type on every render, so React would unmount and remount all
 * ~188 rows on each keystroke in the search box.
 */
function ModuleRow({
  mod,
  displayName,
  blockers,
  alsoInstalls,
  locked,
  busy,
  onToggle,
}: {
  mod: SettingsModule;
  displayName: string;
  blockers: string[];
  alsoInstalls: string[];
  locked: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex items-start justify-between gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-content-primary">{displayName}</span>
          {mod.is_core && (
            <Badge variant="blue" size="sm">
              {t('settings.modules_core_badge', { defaultValue: 'Always on' })}
            </Badge>
          )}
          <span className="text-2xs text-content-quaternary tabular-nums">v{mod.version}</span>
        </div>
        {mod.description && (
          <p className="mt-0.5 text-xs text-content-tertiary">{mod.description}</p>
        )}
        {blockers.length > 0 && (
          <p className="mt-1 flex items-start gap-1 text-xs text-semantic-warning">
            <Lock size={12} className="mt-0.5 shrink-0" aria-hidden />
            <span>
              {t('settings.modules_required_by', {
                defaultValue: 'Required by: {{names}}',
                names: fmtList(blockers),
              })}
            </span>
          </p>
        )}
        {alsoInstalls.length > 0 && (
          <p className="mt-1 text-xs text-content-tertiary">
            {t('settings.modules_will_install', {
              defaultValue: 'Installing this also installs: {{names}}',
              names: fmtList(alsoInstalls),
            })}
          </p>
        )}
      </div>
      <ModuleToggle
        enabled={mod.enabled}
        disabled={locked}
        busy={busy}
        label={displayName}
        onToggle={onToggle}
      />
    </div>
  );
}

/* ── Panel ───────────────────────────────────────────────────────────────── */

export function ModulesSettings() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const isAdmin = userRole === 'admin';
  const { confirm, ...confirmProps } = useConfirm();

  const [query, setQuery] = useState('');
  const [busyModule, setBusyModule] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [showCore, setShowCore] = useState(false);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['system-modules'],
    queryFn: () => apiGet<SettingsModule[]>('/v1/modules/'),
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
  });

  const modules = useMemo(() => data ?? [], [data]);

  /** Name lookup, used by both dependency directions below. */
  const byName = useMemo(() => {
    const map = new Map<string, SettingsModule>();
    for (const m of modules) map.set(m.name, m);
    return map;
  }, [modules]);

  /**
   * Reverse dependency index: module name -> modules that require it.
   *
   * The backend exposes this per module at `/v1/modules/dependency-tree/{name}`,
   * but every input it uses (`depends` of every manifest) is already in the one
   * list response, and asking per row would be 188 requests to render one
   * screen. Same computation, same answer, one fetch.
   */
  const dependents = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const m of modules) {
      for (const dep of m.depends) {
        const list = map.get(dep);
        if (list) list.push(m.name);
        else map.set(dep, [m.name]);
      }
    }
    return map;
  }, [modules]);

  const nameOf = useCallback(
    (mod: SettingsModule) => resolveModuleDisplayName(mod, t, i18n.language),
    [t, i18n.language],
  );

  /** Enabled modules that would break if `mod` were removed. */
  const blockingDependents = useCallback(
    (mod: SettingsModule): SettingsModule[] =>
      (dependents.get(mod.name) ?? [])
        .map((n) => byName.get(n))
        .filter((m): m is SettingsModule => !!m && m.enabled),
    [dependents, byName],
  );

  /** Currently-disabled modules that installing `mod` would pull in with it. */
  const pendingDependencies = useCallback(
    (mod: SettingsModule): SettingsModule[] =>
      mod.depends
        .map((n) => byName.get(n))
        .filter((m): m is SettingsModule => !!m && !m.enabled),
    [byName],
  );

  const optional = useMemo(() => modules.filter((m) => !m.is_core), [modules]);
  const core = useMemo(() => modules.filter((m) => m.is_core), [modules]);
  const installedCount = useMemo(() => optional.filter((m) => m.enabled).length, [optional]);

  const needle = query.trim().toLowerCase();
  const matches = useCallback(
    (mod: SettingsModule) => {
      if (!needle) return true;
      return (
        nameOf(mod).toLowerCase().includes(needle) ||
        mod.name.toLowerCase().includes(needle) ||
        mod.description.toLowerCase().includes(needle)
      );
    },
    [needle, nameOf],
  );

  /** Optional modules bucketed by category key, each bucket name-sorted. */
  const groups = useMemo(() => {
    const buckets = new Map<string, SettingsModule[]>();
    for (const mod of optional) {
      if (!matches(mod)) continue;
      const key = categoryKey(mod.category);
      const list = buckets.get(key);
      if (list) list.push(mod);
      else buckets.set(key, [mod]);
    }
    const collator = new Intl.Collator(i18n.language);
    return [...buckets.entries()]
      .map(([key, list]) => ({
        key,
        modules: [...list].sort((a, b) => collator.compare(nameOf(a), nameOf(b))),
      }))
      .sort((a, b) =>
        collator.compare(
          t(a.key, { defaultValue: CATEGORY_DEFAULTS[a.key] ?? '' }),
          t(b.key, { defaultValue: CATEGORY_DEFAULTS[b.key] ?? '' }),
        ),
      );
  }, [optional, matches, nameOf, i18n.language, t]);

  const visibleCore = useMemo(() => {
    const collator = new Intl.Collator(i18n.language);
    return core.filter(matches).sort((a, b) => collator.compare(nameOf(a), nameOf(b)));
  }, [core, matches, nameOf, i18n.language]);

  const toggleGroup = useCallback((key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  async function handleToggle(mod: SettingsModule): Promise<void> {
    if (!isAdmin || mod.is_core) return;

    if (mod.enabled) {
      // Pre-empt the server's 400. `disable_module` refuses outright when an
      // enabled module still lists this one in `depends`, and letting that
      // land as a red toast after the click reads as a bug rather than a rule.
      const blockers = blockingDependents(mod);
      if (blockers.length > 0) {
        addToast({
          type: 'warning',
          title: t('settings.modules_blocked_title', { defaultValue: 'Cannot remove' }),
          message: t('settings.modules_required_by', {
            defaultValue: 'Required by: {{names}}',
            names: fmtList(blockers.map(nameOf)),
          }),
        });
        return;
      }
      const confirmed = await confirm({
        title: t('settings.modules_confirm_remove_title', {
          defaultValue: 'Remove {{name}}?',
          name: nameOf(mod),
        }),
        message: t('settings.modules_confirm_remove', {
          defaultValue:
            'Its screens and API routes stop being served for everyone on this instance. Your data is kept, and installing it again brings the module back.',
        }),
        confirmLabel: t('settings.modules_remove', { defaultValue: 'Remove' }),
        variant: 'warning',
      });
      if (!confirmed) return;
    }

    const action = mod.enabled ? 'disable' : 'enable';
    const alsoInstalls = action === 'enable' ? pendingDependencies(mod) : [];
    setBusyModule(mod.name);
    try {
      await apiPost<{ name: string; status: string }>(`/v1/modules/${mod.name}/${action}`);
      addToast({
        type: 'success',
        title:
          action === 'enable'
            ? t('settings.modules_installed_toast', {
                defaultValue: '{{name}} installed',
                name: nameOf(mod),
              })
            : t('settings.modules_removed_toast', {
                defaultValue: '{{name}} removed',
                name: nameOf(mod),
              }),
        // `enable_module` walks `depends` and installs whatever is missing, so
        // say which ones came along instead of leaving the count to surprise.
        message:
          alsoInstalls.length > 0
            ? t('settings.modules_also_installed', {
                defaultValue: 'Also installed: {{names}}',
                names: fmtList(alsoInstalls.map(nameOf)),
              })
            : undefined,
      });
      void queryClient.invalidateQueries({ queryKey: ['system-modules'] });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('settings.modules_toggle_failed', { defaultValue: 'Could not change the module' }),
        message:
          err instanceof Error
            ? err.message
            : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setBusyModule(null);
    }
  }

  /** Everything a row needs, resolved here so the row itself stays dumb. */
  const rowFor = useCallback(
    (mod: SettingsModule) => {
      const blockers = mod.enabled && !mod.is_core ? blockingDependents(mod) : [];
      const alsoInstalls = !mod.enabled ? pendingDependencies(mod) : [];
      return (
        <ModuleRow
          key={mod.name}
          mod={mod}
          displayName={nameOf(mod)}
          blockers={blockers.map(nameOf)}
          alsoInstalls={alsoInstalls.map(nameOf)}
          locked={mod.is_core || !isAdmin || blockers.length > 0}
          busy={busyModule === mod.name}
          onToggle={() => void handleToggle(mod)}
        />
      );
    },
    // `handleToggle` is a plain function declaration recreated each render and
    // is intentionally not a dependency: it only reads state that changes in
    // lockstep with the values already listed here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [blockingDependents, pendingDependencies, nameOf, isAdmin, busyModule],
  );

  /* ── Render ────────────────────────────────────────────────────────────── */

  if (isError) {
    return (
      <Card>
        <CardContent>
          <div className="py-12 text-center">
            <AlertTriangle
              size={36}
              className="mx-auto mb-3 text-semantic-warning"
              strokeWidth={1.5}
              aria-hidden
            />
            <p className="text-sm font-medium text-content-secondary">
              {t('settings.modules_load_failed', {
                defaultValue: 'Could not load the module list',
              })}
            </p>
            <Button variant="secondary" size="sm" className="mt-4" onClick={() => void refetch()}>
              {t('common.retry', { defaultValue: 'Retry' })}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Package size={18} className="shrink-0 text-oe-blue" aria-hidden />
              {t('settings.modules_optional_title', { defaultValue: 'Installed modules' })}
            </span>
          }
          subtitle={t('settings.modules_intro', {
            defaultValue:
              'Modules add screens and API endpoints to this instance. Removing one stops it being served for everyone here; it does not delete anything you have entered.',
          })}
        />
        <CardContent>
          {/* Summary + search */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-content-secondary">
              {/* Phrased as a label rather than "{{n}} modules" on purpose:
                  a number sitting directly in front of a noun needs plural
                  agreement in most of the 43 locales, and i18next prints the
                  English form when a language's plural category is missing. */}
              {t('settings.modules_installed_ratio', {
                defaultValue: 'Optional modules installed: {{installed}} of {{total}}',
                installed: installedCount,
                total: optional.length,
              })}
            </p>
            <div className="relative sm:w-64">
              <Search
                size={15}
                className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-quaternary"
                aria-hidden
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('settings.modules_search', { defaultValue: 'Search modules' })}
                aria-label={t('settings.modules_search', { defaultValue: 'Search modules' })}
                className="w-full rounded-lg border border-border-light bg-surface-primary py-2 ps-9 pe-3 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none"
              />
            </div>
          </div>

          {!isAdmin && (
            <div className="mt-4 flex items-start gap-2 rounded-lg bg-surface-secondary px-3 py-2.5">
              <Info size={15} className="mt-0.5 shrink-0 text-content-tertiary" aria-hidden />
              <p className="text-xs text-content-secondary">
                {t('settings.modules_admin_only_hint', {
                  defaultValue:
                    'Only an administrator can install or remove modules. You can see what is installed here.',
                })}
              </p>
            </div>
          )}

          {isLoading && (
            <p className="mt-6 text-sm text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          )}

          {!isLoading && groups.length === 0 && (
            <p className="mt-6 text-sm text-content-tertiary">
              {t('settings.modules_no_results', {
                defaultValue: 'No module matches your search.',
              })}
            </p>
          )}

          {/* Optional modules, grouped by category */}
          <div className="mt-4 space-y-3">
            {groups.map((group) => {
              const isCollapsed = collapsed.has(group.key) && !needle;
              const enabledInGroup = group.modules.filter((m) => m.enabled).length;
              return (
                <div
                  key={group.key}
                  className="overflow-hidden rounded-xl border border-border-light"
                >
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.key)}
                    aria-expanded={!isCollapsed}
                    className="flex w-full items-center justify-between gap-3 bg-surface-secondary px-4 py-2.5 text-left hover:bg-surface-tertiary"
                  >
                    <span className="flex items-center gap-2">
                      {isCollapsed ? (
                        <ChevronRight size={15} className="text-content-tertiary" aria-hidden />
                      ) : (
                        <ChevronDown size={15} className="text-content-tertiary" aria-hidden />
                      )}
                      <span className="text-sm font-semibold text-content-primary">
                        {t(group.key, { defaultValue: CATEGORY_DEFAULTS[group.key] ?? '' })}
                      </span>
                    </span>
                    <span className="text-xs tabular-nums text-content-tertiary">
                      {enabledInGroup} / {group.modules.length}
                    </span>
                  </button>
                  {!isCollapsed && (
                    <div className="divide-y divide-border-light/50">
                      {group.modules.map((mod) => rowFor(mod))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Core modules — shown so the list is complete, collapsed so 119
          permanently-locked rows do not bury the ~69 that can be changed. */}
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Lock size={18} className="shrink-0 text-content-tertiary" aria-hidden />
              {t('settings.modules_core_title', { defaultValue: 'Always-on modules' })}
            </span>
          }
          subtitle={t('settings.modules_core_hint', {
            defaultValue:
              'These are part of the platform itself. They cannot be removed, because the rest of the system is built on them.',
          })}
        />
        <CardContent>
          <button
            type="button"
            onClick={() => setShowCore((v) => !v)}
            aria-expanded={showCore}
            className="flex items-center gap-2 text-sm font-medium text-oe-blue hover:underline"
          >
            {showCore ? <ChevronDown size={15} aria-hidden /> : <ChevronRight size={15} aria-hidden />}
            {showCore
              ? t('settings.modules_core_hide', { defaultValue: 'Hide always-on modules' })
              : t('settings.modules_core_show', {
                  defaultValue: 'Show always-on modules ({{total}})',
                  total: core.length,
                })}
          </button>
          {showCore && (
            <div className="mt-3 overflow-hidden rounded-xl border border-border-light divide-y divide-border-light/50">
              {visibleCore.map((mod) => rowFor(mod))}
              {visibleCore.length === 0 && (
                <p className="px-4 py-3 text-sm text-content-tertiary">
                  {t('settings.modules_no_results', {
                    defaultValue: 'No module matches your search.',
                  })}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pointers to the two neighbouring surfaces, so nobody hunts for the
          marketplace here or expects this panel to tidy their sidebar. */}
      <Card>
        <CardContent>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-medium text-content-primary">
                {t('settings.modules_registry_title', { defaultValue: 'Module registry' })}
              </p>
              <p className="mt-0.5 text-xs text-content-tertiary">
                {t('settings.modules_registry_hint', {
                  defaultValue:
                    'Ready-made industry packs, the module builder and the developer guide live on their own page.',
                })}
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigate('/modules')}
              icon={<ArrowUpRight size={15} />}
              iconPosition="right"
            >
              {t('settings.modules_open_registry', { defaultValue: 'Open registry' })}
            </Button>
          </div>
          <p className="mt-4 border-t border-border-light pt-3 text-xs text-content-tertiary">
            {t('settings.modules_menu_hint', {
              defaultValue:
                'Looking to tidy your own menu rather than change the instance? Use "Edit menu" at the bottom of the sidebar - that hides entries for you alone and leaves every module installed.',
            })}
          </p>
        </CardContent>
      </Card>

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
