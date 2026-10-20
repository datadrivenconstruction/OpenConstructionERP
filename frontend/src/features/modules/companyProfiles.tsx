// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Company profiles (company-type presets): their data, the switch, and the
 * card and confirm dialog that show them.
 *
 * Two screens offer a profile: the Modules page's Company Profiles tab and the
 * Packs page, where a profile is the company-type half of a setup. Both read
 * this one hook, so the switch writes the same record the same way wherever
 * the reader presses it.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Box,
  Boxes,
  Briefcase,
  Building2,
  Calculator,
  Check,
  ClipboardList,
  HardHat,
  Home,
  Package,
  Pencil,
  type LucideIcon,
} from 'lucide-react';
import { Badge, ConfirmDialog } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { type MeOnboarding } from '@/app/layout/useCompanyWorkspace';
import { useMeOnboardingQueryKey } from '@/app/layout/meOnboardingQuery';
import { getModulesByCategory } from '@/modules/_registry';
import { resolveModuleDisplayName } from './moduleDisplayName';
import { profileDelta, profileShapes, type ProfileShape } from './profileDifference';

export interface CompanyPresetAPI {
  key: string;
  label: string;
  description: string;
  icon: string;
  tags?: string[];
  enabled_modules: string[];
  module_count: number;
}

/** The profile that switches every module on; it sorts first and is the
 *  way back from any narrower profile. */
export const FULL_PROFILE_KEY = 'full_enterprise';

const PRESET_ICON_MAP: Record<string, LucideIcon> = {
  Building2, Calculator, ClipboardList, Pencil, Boxes,
  Home, HardHat, Briefcase, Box,
};

export function getPresetIcon(iconName: string): LucideIcon {
  return PRESET_ICON_MAP[iconName] ?? Package;
}

/**
 * The name a preset's module key wears on screen.
 *
 * Presets speak in bare keys (`supplier_catalogs`), the locale files carry
 * `modules.catalog.supplier_catalogs`, and `moduleDisplayNameKey` already
 * derives one from the other for the registry page. Reusing it means the
 * profile cards and the module registry cannot end up calling the same module
 * two different things.
 *
 * The fallback is the key with its underscores opened out rather than the raw
 * key, because a card reading "supplier_catalogs" tells a reader they are
 * looking at a bug.
 */
export function presetModuleName(
  t: (key: string, options: { defaultValue: string }) => string,
  language: string,
  id: string,
): string {
  return resolveModuleDisplayName({ name: id, display_name: id.replace(/_/g, ' ') }, t, language);
}

/** Full platform first, the rest in the order the server lists them. */
export function sortPresets(presets: readonly CompanyPresetAPI[]): CompanyPresetAPI[] {
  return [...presets].sort((a, b) => (a.key === FULL_PROFILE_KEY ? -1 : b.key === FULL_PROFILE_KEY ? 1 : 0));
}

/** The localised name of a profile. */
export function useProfileName() {
  const { t } = useTranslation();
  return useCallback(
    (preset: Pick<CompanyPresetAPI, 'key' | 'label'>) =>
      t(`onboarding.company_${preset.key}`, { defaultValue: preset.label }),
    [t],
  );
}

export function useCompanyProfiles() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const onboardingQueryKey = useMeOnboardingQueryKey();
  const addToast = useToastStore((s) => s.addToast);
  const syncFromServer = useModuleStore((s) => s.syncFromServer);
  const profileName = useProfileName();

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

  const presetsQuery = useQuery({
    queryKey: ['onboarding-presets'],
    queryFn: () => apiGet<CompanyPresetAPI[]>('/v1/users/onboarding-presets/'),
  });
  const presets = presetsQuery.data;

  // The modules no profile governs. Asked for rather than copied, because a
  // copy here and the list in `onboarding_presets.py` would drift, and the
  // direction it drifts in decides whether this page tells a reader they are
  // about to lose Projects. An empty answer degrades to naming a few more
  // modules in the delta, never to hiding one.
  const { data: coreModules } = useQuery({
    queryKey: ['onboarding-presets', 'core'],
    queryFn: () =>
      apiGet<{ core_modules: string[] }>('/v1/users/onboarding-presets/core/').then(
        (r) => r.core_modules,
      ),
    staleTime: 60 * 60 * 1000,
  });

  // What each profile carries that few others do. Computed over the whole set
  // because "particular to this one" is a claim about the other twenty-one,
  // and there is no way to make it from a single card's own data.
  const shapes = useMemo(
    () => profileShapes(presets ?? [], coreModules ?? []),
    [presets, coreModules],
  );

  const requestSwitch = useCallback(
    (preset: CompanyPresetAPI) => {
      if (preset.key === activeProfileKey) return;
      setSwitchingTo(preset);
    },
    [activeProfileKey],
  );
  const cancelSwitch = useCallback(() => setSwitchingTo(null), []);

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
      const isFullEnterprise = switchingTo.key === FULL_PROFILE_KEY;
      const enabledModules = isFullEnterprise
        ? Object.values(getModulesByCategory()).flatMap((mods) => mods.map((m) => m.id))
        : switchingTo.enabled_modules;

      // No `interface_mode`: the Simple / Advanced choice has its own per-user
      // record (`/v1/users/me/view-mode/`), and this field used to be written
      // as 'advanced' on every switch whatever mode the user was in. A user
      // who never picked a mode gets the default the new profile implies
      // (`app/layout/useViewModeDefault.ts`).
      const saved = await apiPost<MeOnboarding>('/v1/users/me/onboarding/', {
        company_type: switchingTo.key,
        enabled_modules: enabledModules,
        completed: true,
      });
      // The sidebar picks its Simple-mode workspace from the profile in this
      // cache entry, so a switch reshapes the menu now, not after it goes stale.
      queryClient.setQueryData(onboardingQueryKey, saved);

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
  }, [switchingTo, syncFromServer, addToast, t, queryClient, onboardingQueryKey]);

  const activePreset = presets?.find((p) => p.key === activeProfileKey);

  // What the pending switch would actually do. Computed against the profile in
  // force, so an account that has never picked one gets "everything gained,
  // nothing lost", which is the truth rather than a diff against an invented
  // baseline.
  const switchDelta = useMemo(
    () =>
      switchingTo
        ? profileDelta(activePreset ?? null, switchingTo, coreModules ?? [])
        : { gained: [], lost: [], kept: [] },
    [switchingTo, activePreset, coreModules],
  );

  return {
    presets,
    presetsLoading: presetsQuery.isLoading,
    presetsError: presetsQuery.isError,
    refetchPresets: presetsQuery.refetch,
    coreModules,
    shapes,
    activeProfileKey,
    activePreset,
    switchingTo,
    isSwitching,
    switchDelta,
    requestSwitch,
    cancelSwitch,
    confirmSwitch,
    profileName,
  };
}

export type CompanyProfilesState = ReturnType<typeof useCompanyProfiles>;

/** The confirm step of a profile switch, with what it turns on and off. */
export function ProfileSwitchDialog({ state }: { state: CompanyProfilesState }) {
  const { t } = useTranslation();
  const { switchingTo, switchDelta, coreModules, isSwitching, profileName } = state;
  return (
    <ConfirmDialog
      open={switchingTo !== null}
      onConfirm={() => void state.confirmSwitch()}
      onCancel={state.cancelSwitch}
      title={t('modules.switch_profile_title', {
        defaultValue: 'Switch Profile',
      })}
      message={t('modules.switch_profile_delta', {
        // A new key rather than new wording on the old one. The old string is
        // already translated into forty-one languages, and adding
        // placeholders to the English alone would have left every other
        // reader the sentence without the numbers, which no gate we own can
        // see. Counts follow a colon so no language owes this string a plural
        // form.
        defaultValue:
          'Switch to {{name}}? Turned on: {{gained}}. Turned off: {{lost}}. Kept: {{kept}}. Never changed by a profile: {{core}}.',
        name: switchingTo ? profileName(switchingTo) : '',
        gained: switchDelta.gained.length,
        lost: switchDelta.lost.length,
        kept: switchDelta.kept.length,
        core: coreModules?.length ?? 0,
      })}
      confirmLabel={t('modules.switch_confirm', { defaultValue: 'Switch Profile' })}
      variant="warning"
      loading={isSwitching}
    />
  );
}

/** One company profile as a pressable card. */
export function CompanyProfileCard({
  preset,
  isActive,
  shape,
  onSelect,
  className,
}: {
  preset: CompanyPresetAPI;
  isActive: boolean;
  shape: ProfileShape | undefined;
  onSelect: (preset: CompanyPresetAPI) => void;
  className?: string;
}) {
  const { t, i18n } = useTranslation();
  const Icon = getPresetIcon(preset.icon);
  const isFull = preset.key === FULL_PROFILE_KEY;
  const name = t(`onboarding.company_${preset.key}`, { defaultValue: preset.label });
  return (
    <button
      type="button"
      onClick={() => onSelect(preset)}
      aria-label={`${name} - ${preset.module_count} ${t('modules.modules_label', { defaultValue: 'modules' })}`}
      aria-pressed={isActive}
      data-profile-key={preset.key}
      className={clsx(
        'text-start rounded-xl border p-4 transition-all',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        isActive
          ? 'border-oe-blue bg-oe-blue-subtle ring-1 ring-oe-blue/30'
          : isFull
            ? 'border-emerald-300 bg-emerald-50/60 hover:border-emerald-400 hover:shadow-xs dark:border-emerald-700 dark:bg-emerald-950/30 dark:hover:border-emerald-600'
            : 'border-border-light bg-surface-elevated hover:border-border hover:shadow-xs',
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={clsx(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
            isActive ? 'bg-oe-blue/10 text-oe-blue' : isFull ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-400' : 'bg-surface-secondary text-content-secondary',
          )}
        >
          <Icon size={20} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-content-primary">{name}</span>
            {isActive && (
              <Badge variant="success" size="sm">
                <Check size={10} className="me-0.5" />
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
          {/* What this profile is for, said in modules rather than in
              adjectives. Two names, because the point is to be read
              at a glance across a grid of twenty-two cards; the rest
              of the list is on the profile itself. */}
          {(() => {
            const rare = shape?.rare ?? [];
            if (rare.length === 0) return null;
            const shown = rare.slice(0, 2).map((id) => presetModuleName(t, i18n.language, id));
            return (
              <p className="mt-1 text-2xs text-content-tertiary">
                <span className="font-medium">
                  {t('modules.profile_particular', { defaultValue: 'Particular to it' })}:
                </span>{' '}
                {fmtList(shown)}
                {rare.length > shown.length && (
                  <span className="text-content-tertiary">
                    {' '}
                    {/* `n`, not `count`. i18next reads `count` as a
                        plural selector, which would make this one
                        string owe every locale its own CLDR forms
                        for a number that only ever follows a plus
                        sign. */}
                    {t('modules.profile_particular_more', {
                      defaultValue: '+{{n}}',
                      n: rare.length - shown.length,
                    })}
                  </span>
                )}
              </p>
            );
          })()}
        </div>
      </div>
    </button>
  );
}
