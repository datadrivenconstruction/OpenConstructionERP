// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Finish step's "what was set up" list: one row per choice, each with a
// way back to the step that changes it. Values are read from the same stores
// the app reads, so the list shows what the app will show.

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowRight, Building2, Globe, LayoutGrid, Palette, Users } from 'lucide-react';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { matchPreset } from '@/shared/lib/appearance';
import { matchMenuPreset } from '@/shared/lib/menuAppearance';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { STEP } from './OnboardingStepper';
import { PRESET_NAME } from './StepLook';

function Row({
  id,
  icon,
  label,
  value,
  action,
}: {
  id: string;
  icon: ReactNode;
  label: string;
  value: ReactNode;
  action: ReactNode;
}) {
  return (
    <li data-testid={`setup-summary-${id}`} className="flex items-center gap-3 px-4 py-2.5">
      <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[11px] font-medium uppercase tracking-wide text-content-tertiary">{label}</span>
        <span className="block truncate text-sm text-content-primary">{value}</span>
      </span>
      {action}
    </li>
  );
}

export function SetupSummary({
  packInstalled,
  presetLabel,
  enabledCount,
  language,
  onEdit,
  onLeave,
}: {
  packInstalled: boolean;
  presetLabel: string | null;
  enabledCount: number;
  language: string;
  /** Go back to a wizard step (an index from {@link STEP}). */
  onEdit: (step: number) => void;
  /** Called before a link leaves the wizard, so it is not shown again. */
  onLeave: () => void;
}) {
  const { t } = useTranslation();
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';
  const effective = useAppearanceStore((s) => s.effective);
  const menu = useAppearanceStore((s) => s.menu);
  const { mode, logoDataUrl, companyName } = useBrandingStore();

  const change = (step: number, item: string) => (
    <button
      type="button"
      onClick={() => onEdit(step)}
      aria-label={t('onboarding.summary_change_aria', { defaultValue: 'Change {{item}}', item })}
      className="shrink-0 rounded-lg px-2.5 py-1 text-xs font-semibold text-oe-blue hover:bg-oe-blue/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
    >
      {t('onboarding.summary_change', { defaultValue: 'Change' })}
    </button>
  );

  const styleId = matchPreset(effective);
  const menuId = matchMenuPreset(menu);
  const custom = t('onboarding.summary_custom', { defaultValue: 'Custom' });
  const styleName = styleId ? t(`settings.style_preset_${styleId}`, { defaultValue: PRESET_NAME[styleId] ?? styleId }) : custom;
  const menuName = menuId ? t(`settings.menu_preset_${menuId}`, { defaultValue: PRESET_NAME[menuId] ?? menuId }) : custom;
  const modules = `${enabledCount} ${t('onboarding.modules_label', { defaultValue: 'modules' })}`;

  const labels = {
    language: t('onboarding.summary_language', { defaultValue: 'Language' }),
    profile: t('onboarding.summary_profile', { defaultValue: 'Profile and modules' }),
    look: t('onboarding.summary_look', { defaultValue: 'Look' }),
    brand: t('onboarding.brand_section', { defaultValue: 'Your company' }),
    team: t('onboarding.summary_team', { defaultValue: 'Team' }),
  };
  const customised = mode === 'logo' || mode === 'text';

  return (
    <div className="mt-6 w-full max-w-md text-start">
      <h3 className="mb-2 text-sm font-semibold text-content-primary">
        {t('onboarding.summary_title', { defaultValue: 'What is set up' })}
      </h3>
      <ul
        data-testid="setup-summary"
        className="divide-y divide-border-light overflow-hidden rounded-2xl border border-border-light bg-surface-elevated/70 shadow-sm"
      >
        <Row
          id="language"
          icon={<Globe size={16} />}
          label={labels.language}
          value={SUPPORTED_LANGUAGES.find((l) => l.code === language)?.name || language}
          action={change(STEP.welcome, labels.language)}
        />
        <Row
          id="profile"
          icon={<LayoutGrid size={16} />}
          label={labels.profile}
          value={
            packInstalled
              ? t('onboarding.ready_pack', { defaultValue: 'Ready-made Pack' })
              : presetLabel
                ? `${presetLabel} · ${modules}`
                : modules
          }
          action={change(packInstalled ? STEP.start : STEP.profile, labels.profile)}
        />
        <Row
          id="look"
          icon={<Palette size={16} />}
          label={labels.look}
          value={`${styleName} · ${menuName}`}
          action={change(STEP.look, labels.look)}
        />
        {isAdmin && (
          <Row
            id="brand"
            icon={
              mode === 'logo' && logoDataUrl ? (
                <img src={logoDataUrl} alt="" className="h-full w-full rounded-lg object-contain" draggable={false} />
              ) : (
                <Building2 size={16} />
              )
            }
            label={labels.brand}
            value={
              customised && companyName
                ? companyName
                : mode === 'logo'
                  ? t('onboarding.summary_brand_logo', { defaultValue: 'Logo added' })
                  : t('onboarding.summary_brand_none', { defaultValue: 'Not set yet' })
            }
            action={change(STEP.look, labels.brand)}
          />
        )}
        {isAdmin && (
          <Row
            id="team"
            icon={<Users size={16} />}
            label={labels.team}
            value={t('onboarding.summary_team_hint', { defaultValue: 'Add colleagues and choose their roles' })}
            action={
              <Link
                to="/users"
                onClick={onLeave}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-semibold text-oe-blue hover:bg-oe-blue/10"
              >
                {t('onboarding.summary_team_open', { defaultValue: 'Open' })}
                <ArrowRight size={12} className="rtl:rotate-180" />
              </Link>
            }
          />
        )}
      </ul>
    </div>
  );
}
