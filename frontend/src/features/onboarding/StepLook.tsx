// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Optional wizard step: "How your platform will look". Reads the same presets
// the Settings cards use (APPEARANCE_PRESETS, MENU_PRESETS) and applies through
// the same store, so there is one source of truth. Nothing is applied until
// "Apply"; the mini preview renders the draft.

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ArrowRight, Check } from 'lucide-react';
import { Button } from '@/shared/ui';
import { apiPut } from '@/shared/lib/api';
import {
  ACCENTS,
  ACCENT_SWATCH,
  APPEARANCE_PRESETS,
  FONT_STACK,
  ensureFontLoaded,
  matchPreset,
  type Appearance,
} from '@/shared/lib/appearance';
import { MENU_PRESETS, matchMenuPreset, type MenuLook } from '@/shared/lib/menuAppearance';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { useToastStore } from '@/stores/useToastStore';
import { BrandDraftSection, type BrandDraft } from './BrandDraft';

const RADIUS_PX: Record<Appearance['radius'], number> = { sharp: 2, standard: 6, round: 12 };

export const PRESET_NAME: Record<string, string> = {
  classic: 'Classic',
  studio: 'Studio',
  engineering: 'Engineering',
  warm: 'Warm',
  executive: 'Executive',
  blueprint: 'Blueprint',
  site_office: 'Site office',
  focus: 'Focus',
};

/** A drawing of the sidebar for one menu look; `k` scales it. */
function MenuSchematic({ look, accent, k = 1, fill = false }: { look: MenuLook; accent: string; k?: number; fill?: boolean }) {
  const rail = look.view === 'rail';
  const floating = look.view === 'floating';
  const rowH = (look.view === 'compact' ? 5 : look.view === 'comfortable' ? 9 : 7) * k;
  const gap = (look.view === 'compact' ? 2 : look.view === 'comfortable' ? 5 : 3) * k;
  const width = fill ? '100%' : rail ? '22%' : look.view === 'compact' ? '40%' : '48%';
  const showIcons = look.icons === 'shown' || rail;
  const rows = [0, 1, 2, 3];
  return (
    <div
      aria-hidden
      className={`h-full shrink-0 ${floating ? 'p-[3px]' : 'border-e border-border-light bg-surface-secondary'}`}
      style={{ width }}
    >
      <div
        className={`flex h-full flex-col ${floating ? 'rounded-md border border-border-light bg-surface-elevated shadow-sm' : ''}`}
        style={{ padding: 3 * k, gap }}
      >
        {look.headers !== 'none' && !rail && (
          <span
            className={look.headers === 'divider' ? 'border-b border-border' : ''}
            style={{ height: 2 * k, width: '50%', background: look.headers === 'caps' ? 'var(--oe-border, #cbd5e1)' : undefined }}
          />
        )}
        {rows.map((i) => {
          const on = i === 0;
          const bg = !on ? undefined : look.active === 'pill' ? accent : `${accent}26`;
          const fg = on && look.active === 'pill' ? '#fff' : accent;
          return (
            <div
              key={i}
              className="flex items-center"
              style={{
                height: rowH,
                gap: 2 * k,
                paddingInline: 2 * k,
                background: bg,
                borderRadius: look.active === 'bar' ? 0 : 99,
                borderInlineStart: on && look.active === 'bar' ? `${Math.max(1, k)}px solid ${accent}` : undefined,
              }}
            >
              {showIcons && (
                <span
                  className="shrink-0"
                  style={{
                    width: 4 * k,
                    height: 4 * k,
                    background: on ? fg : look.color === 'mono' ? '#94a3b8' : accent,
                    borderRadius: look.container === 'circle' ? 99 : look.container === 'tile' ? 1.5 * k : 1,
                    opacity: look.stroke === 'light' ? 0.6 : 1,
                  }}
                />
              )}
              {!rail && (
                <span className="block flex-1 rounded-full" style={{ height: 2 * k, background: on ? fg : '#94a3b8', opacity: on ? 1 : 0.7 }} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** The scaled app shell: sidebar, header and a card, in the draft's tokens. */
function LookPreview({
  style,
  menu,
  label,
  brand,
}: {
  style: Appearance;
  menu: MenuLook;
  label: string;
  brand?: BrandDraft;
}) {
  const { t } = useTranslation();
  const accent = ACCENT_SWATCH[style.accent];
  const r = RADIUS_PX[style.radius];
  const pad = style.density === 'compact' ? 6 : 10;
  return (
    <div
      role="group"
      aria-label={label}
      data-testid="look-preview"
      data-accent={style.accent}
      data-font={style.font}
      data-radius={style.radius}
      data-density={style.density}
      data-view={menu.view}
      className="flex h-56 w-full overflow-hidden border border-border bg-surface-primary shadow-sm"
      style={{ borderRadius: r + 4, fontFamily: FONT_STACK[style.font] }}
    >
      <div
        className="flex shrink-0 flex-col"
        style={{ width: menu.view === 'rail' ? '14%' : menu.view === 'compact' ? '28%' : '34%' }}
      >
        {brand && (brand.logo || brand.name.trim()) && (
          <div
            data-testid="look-preview-brand"
            className="flex h-8 shrink-0 items-center overflow-hidden border-b border-e border-border-light bg-surface-secondary px-1.5"
          >
            {brand.logo ? (
              <img src={brand.logo} alt="" className="block max-h-5 w-auto max-w-full object-contain" draggable={false} />
            ) : (
              <span className="truncate text-[10px] font-extrabold text-content-primary">{brand.name.trim()}</span>
            )}
          </div>
        )}
        <div className="min-h-0 flex-1">
          <MenuSchematic look={menu} accent={accent} k={1.5} fill />
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-8 items-center justify-between border-b border-border-light bg-surface-elevated px-2.5">
          <span className="truncate text-[11px] font-semibold text-content-primary">
            {t('onboarding.look_mock_header', { defaultValue: 'Project overview' })}
          </span>
          <span aria-hidden className="h-3 w-3 rounded-full" style={{ background: accent }} />
        </div>
        <div className="flex-1" style={{ padding: pad }}>
          <div className="border border-border-light bg-surface-elevated" style={{ borderRadius: r, padding: pad }}>
            <span className="block truncate text-[11px] font-semibold text-content-primary">
              {t('onboarding.look_mock_card', { defaultValue: 'Budget' })}
            </span>
            <span aria-hidden className="mt-2 block h-1.5 w-full rounded-full bg-border-light">
              <span className="block h-full w-2/3 rounded-full" style={{ background: accent }} />
            </span>
            <span aria-hidden className="mt-2 block h-1.5 w-1/2 rounded-full bg-border-light" />
            <span
              aria-hidden
              className="mt-3 inline-block h-4 w-14"
              style={{ background: accent, borderRadius: r }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Radio group with roving tabindex and arrow-key selection (RTL aware). */
function RadioRow({
  label,
  children,
  className = '',
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const keys = ['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp'];
    if (!keys.includes(e.key)) return;
    const radios = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]') ?? []);
    if (radios.length === 0) return;
    const rtl = ref.current ? getComputedStyle(ref.current).direction === 'rtl' : false;
    const forward = e.key === 'ArrowDown' || e.key === (rtl ? 'ArrowLeft' : 'ArrowRight');
    const at = radios.findIndex((b) => b === document.activeElement);
    const next = radios[(Math.max(at, 0) + (forward ? 1 : -1) + radios.length) % radios.length];
    e.preventDefault();
    next?.focus();
    next?.click();
  };
  return (
    <div role="radiogroup" aria-label={label} ref={ref} onKeyDown={onKeyDown} className={className}>
      {children}
    </div>
  );
}

const RING =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2 focus-visible:ring-offset-surface-primary';

function CardRadio({
  checked,
  tabStop,
  label,
  onSelect,
  children,
}: {
  checked: boolean;
  tabStop: boolean;
  label: string;
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      aria-label={label}
      tabIndex={tabStop ? 0 : -1}
      onClick={onSelect}
      className={`flex w-full shrink-0 flex-col gap-1.5 rounded-lg sm:w-28 border-2 p-2 text-start transition-colors ${RING} ${
        checked ? 'border-oe-blue bg-oe-blue-subtle' : 'border-border-light hover:border-border'
      }`}
    >
      {children}
      <span className="flex items-center justify-between gap-1 text-xs font-medium text-content-primary">
        <span className="truncate">{label}</span>
        {checked && <Check size={12} className="shrink-0 text-oe-blue-text" />}
      </span>
    </button>
  );
}

export function StepLook({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const { t } = useTranslation();
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';
  const [style, setStyle] = useState<Appearance>(() => useAppearanceStore.getState().effective);
  const [menu, setMenu] = useState<MenuLook>(() => useAppearanceStore.getState().menu);
  const [saving, setSaving] = useState(false);
  // The brand is a workspace setting: only an admin sets it, as in Settings.
  const [brandStart] = useState<BrandDraft>(() => {
    const b = useBrandingStore.getState();
    return { logo: b.logoDataUrl, png: b.logoPngDataUrl, name: b.companyName };
  });
  const [brand, setBrand] = useState<BrandDraft>(brandStart);
  const brandChanged = isAdmin && (brand.logo !== brandStart.logo || brand.name.trim() !== brandStart.name.trim());

  useEffect(() => {
    ensureFontLoaded(style.font);
  }, [style.font]);

  const styleId = matchPreset(style);
  const menuId = matchMenuPreset(menu);
  const styleName = (id: string) =>
    t(`settings.style_preset_${id}`, { defaultValue: PRESET_NAME[id] ?? id });
  const menuName = (id: string) =>
    t(`settings.menu_preset_${id}`, { defaultValue: PRESET_NAME[id] ?? id });

  const applyBrand = async () => {
    const b = useBrandingStore.getState();
    // Name first: a name set beside a logo keeps the logo as the brand.
    if (brand.name.trim() !== b.companyName) b.setCompanyName(brand.name);
    if (brand.logo !== b.logoDataUrl) b.setLogo(brand.logo, brand.png);
    if (!(await useBrandingStore.getState().persistToServer())) {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('settings.brand_failed', { defaultValue: 'Could not save the logo' }),
      });
    }
  };

  const apply = async () => {
    const store = useAppearanceStore.getState();
    store.setAppearance(style);
    store.setMenu(menu);
    if (isAdmin) {
      setSaving(true);
      try {
        await apiPut('/v1/branding/', { appearance: { ...style, menu } });
        store.setWorkspaceDefault(style);
        store.setWorkspaceMenu(menu);
      } catch {
        useToastStore.getState().addToast({
          type: 'error',
          title: t('settings.style_workspace_failed', { defaultValue: 'Could not save the workspace default' }),
        });
      }
      if (brandChanged) await applyBrand();
      setSaving(false);
    }
    onNext();
  };

  const stylesLabel = t('onboarding.look_styles', { defaultValue: 'Colour style' });
  const menusLabel = t('onboarding.look_menus', { defaultValue: 'Menu view' });
  const accentLabel = t('onboarding.look_accent', { defaultValue: 'Accent colour' });
  const previewLabel = t('onboarding.look_preview', { defaultValue: 'Preview' });

  return (
    <div>
      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.look_title', { defaultValue: 'How your platform will look' })}
      </h2>
      <p className="mt-1 text-sm text-content-secondary">
        {t('onboarding.look_subtitle', {
          defaultValue: 'Pick a style and a menu. The preview shows the result before anything is applied. This step is optional.',
        })}
      </p>

      <div className="mt-5 grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
        <div className="min-w-0 space-y-5">
          {isAdmin && <BrandDraftSection draft={brand} onChange={setBrand} />}

          <section>
            <h3 className="mb-2 text-sm font-semibold text-content-primary">{stylesLabel}</h3>
            <RadioRow label={stylesLabel} className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
              {APPEARANCE_PRESETS.map((p, i) => (
                <CardRadio
                  key={p.id}
                  checked={styleId === p.id}
                  tabStop={styleId === p.id || (styleId === null && i === 0)}
                  label={styleName(p.id)}
                  onSelect={() => setStyle(p.value)}
                >
                  <span
                    aria-hidden
                    className="flex h-10 items-end gap-1 border border-border-light bg-surface-elevated p-1.5"
                    style={{ borderRadius: RADIUS_PX[p.value.radius] + 2, fontFamily: FONT_STACK[p.value.font] }}
                  >
                    <span className="text-sm font-bold leading-none text-content-primary">Aa</span>
                    <span className="ms-auto h-3 w-5" style={{ background: ACCENT_SWATCH[p.value.accent], borderRadius: RADIUS_PX[p.value.radius] }} />
                  </span>
                </CardRadio>
              ))}
            </RadioRow>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-content-primary">{menusLabel}</h3>
            <RadioRow label={menusLabel} className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
              {MENU_PRESETS.map((p, i) => (
                <CardRadio
                  key={p.id}
                  checked={menuId === p.id}
                  tabStop={menuId === p.id || (menuId === null && i === 0)}
                  label={menuName(p.id)}
                  onSelect={() => setMenu(p.value)}
                >
                  <span
                    aria-hidden
                    className="flex h-12 overflow-hidden rounded border border-border-light bg-surface-elevated"
                    data-testid={`look-menu-${p.id}`}
                  >
                    <MenuSchematic look={p.value} accent={ACCENT_SWATCH[style.accent]} />
                  </span>
                </CardRadio>
              ))}
            </RadioRow>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-content-primary">{accentLabel}</h3>
            <RadioRow label={accentLabel} className="flex flex-wrap gap-2">
              {ACCENTS.map((a) => {
                const name = t(`settings.style_accent_${a}`, { defaultValue: a });
                const on = style.accent === a;
                return (
                  <button
                    key={a}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    aria-label={name}
                    title={name}
                    tabIndex={on ? 0 : -1}
                    onClick={() => setStyle({ ...style, accent: a })}
                    className={`flex h-8 w-8 items-center justify-center rounded-full border-2 ${RING} ${
                      on ? 'border-content-primary' : 'border-transparent'
                    }`}
                  >
                    <span className="flex h-5 w-5 items-center justify-center rounded-full" style={{ background: ACCENT_SWATCH[a] }}>
                      {on && <Check size={12} className="text-white" />}
                    </span>
                  </button>
                );
              })}
            </RadioRow>
          </section>
        </div>

        <div className="min-w-0">
          <h3 className="mb-2 text-sm font-semibold text-content-primary">{previewLabel}</h3>
          <LookPreview style={style} menu={menu} label={previewLabel} brand={isAdmin ? brand : undefined} />
        </div>
      </div>

      <p className="mt-5 text-xs text-content-tertiary">
        {t('onboarding.look_later', {
          defaultValue: 'You can change everything later in Settings > Appearance and Settings > Menu look.',
        })}
        {isAdmin && (
          <>
            {' '}
            {t('onboarding.look_admin_note', {
              defaultValue: 'As an administrator, Apply also makes this the default for your workspace.',
            })}
          </>
        )}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} className="rtl:rotate-180" />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button variant="secondary" onClick={onNext} disabled={saving}>
          {t('onboarding.look_skip', { defaultValue: 'Skip' })}
        </Button>
        <Button
          variant="primary"
          onClick={() => void apply()}
          disabled={saving}
          icon={<ArrowRight size={16} className="rtl:rotate-180" />}
          iconPosition="right"
        >
          {t('onboarding.look_apply', { defaultValue: 'Apply' })}
        </Button>
      </div>
    </div>
  );
}
