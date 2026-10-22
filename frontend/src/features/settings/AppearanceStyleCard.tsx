// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Style" card in Settings > General: a gallery of named styles with live
 * previews, then one control per axis (accent, font, density, corners), plus
 * the personal comfort options (motion, contrast) and one reset.
 *
 * The choice is personal and kept on this device. Admins can also make the
 * current style the workspace default, stored with the workspace branding, which
 * every user without a personal choice follows.
 */
import { useEffect, useId, useState, type CSSProperties, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import { Card, CardHeader, CardContent, Button } from '@/shared/ui';
import { apiPut } from '@/shared/lib/api';
import {
  ACCENTS,
  ACCENT_SWATCH,
  APPEARANCE_PRESETS,
  DENSITIES,
  FONTS,
  FONT_FAMILY_NAME,
  FONT_STACK,
  RADII,
  TEXT_SCALE,
  TEXT_SIZES,
  ensureFontLoaded,
  matchPreset,
  type Appearance,
  type AppearancePreset,
  type FontChoice,
} from '@/shared/lib/appearance';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { checkAccent, normalizeHex } from '@/shared/lib/customAccent';
import {
  CONTRASTS,
  DEFAULT_COMFORT,
  MOTIONS,
  readComfort,
  writeComfort,
  type Comfort,
} from '@/shared/lib/comfort';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

const PREVIEW_RADIUS: Record<Appearance['radius'], number> = { sharp: 3, standard: 8, round: 14 };

function useFontLabel() {
  const { t } = useTranslation();
  return (font: FontChoice) =>
    font === 'system' ? t('settings.style_font_system', { defaultValue: 'System' }) : FONT_FAMILY_NAME[font];
}

/** A miniature window drawn with the style's own accent, font, radius and density. */
function StylePreview({ value, label, active }: { value: Appearance; label: string; active: boolean }) {
  const r = PREVIEW_RADIUS[value.radius];
  const accent = ACCENT_SWATCH[value.accent];
  const gap = value.density === 'compact' ? 4 : 7;
  return (
    <div
      className="flex h-[6.5rem] w-full flex-col justify-between overflow-hidden border border-border-light bg-surface-elevated p-2.5"
      style={{ borderRadius: r + 2, fontFamily: FONT_STACK[value.font] }}
    >
      <div className="flex h-5 items-center justify-between gap-1">
        <span className="truncate text-sm font-semibold leading-tight text-content-primary">{label}</span>
        {active ? (
          <Check size={14} className="shrink-0 text-oe-blue-text" />
        ) : (
          <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: accent }} />
        )}
      </div>
      <div aria-hidden className="flex flex-col" style={{ gap: gap - 2, marginTop: gap }}>
        <span className="h-1.5 w-4/5 bg-border" style={{ borderRadius: r / 2 }} />
        <span className="h-1.5 w-3/5 bg-border" style={{ borderRadius: r / 2 }} />
      </div>
      <div aria-hidden className="flex gap-1.5">
        <span className="h-4 w-12" style={{ background: accent, borderRadius: r }} />
        <span className="h-4 w-8 border border-border" style={{ borderRadius: r }} />
      </div>
    </div>
  );
}

const TEXT_LABEL: Record<(typeof TEXT_SIZES)[number], string> = {
  small: 'Small, 87.5%',
  default: 'Default, 100%',
  large: 'Large, 112.5%',
  larger: 'Larger, 125%',
  largest: 'Largest, 137.5%',
};

export function OptionRow({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div className="grid gap-2 sm:grid-cols-[9rem_1fr] sm:items-center">
      <span id={id} className="text-sm font-medium text-content-primary">
        {label}
      </span>
      <div role="radiogroup" aria-labelledby={id} className="flex flex-wrap gap-2">
        {children}
      </div>
    </div>
  );
}

export function Choice({
  active,
  onSelect,
  label,
  children,
  style,
  onPreview,
}: {
  active: boolean;
  onSelect: () => void;
  label: string;
  children?: ReactNode;
  style?: CSSProperties;
  /** Hover / focus preview: called with true on enter and false on leave. */
  onPreview?: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      aria-label={label}
      onClick={onSelect}
      onMouseEnter={onPreview && (() => onPreview(true))}
      onMouseLeave={onPreview && (() => onPreview(false))}
      onFocus={onPreview && (() => onPreview(true))}
      onBlur={onPreview && (() => onPreview(false))}
      style={style}
      className={`inline-flex min-h-[2.25rem] items-center gap-1.5 rounded-lg border-2 px-3 text-sm font-medium transition-colors duration-normal ease-oe ${
        active
          ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
          : 'border-border-light text-content-secondary hover:border-border hover:text-content-primary'
      }`}
    >
      {children ?? label}
    </button>
  );
}

/** Free company colour: hex input + native picker, with a WCAG AA check on white text. */
function CustomColourRow() {
  const { t } = useTranslation();
  const effective = useAppearanceStore((s) => s.effective);
  const setAccentHex = useAppearanceStore((s) => s.setAccentHex);
  const [draft, setDraft] = useState(effective.accentHex ?? ACCENT_SWATCH[effective.accent]);
  useEffect(() => {
    setDraft(effective.accentHex ?? ACCENT_SWATCH[effective.accent]);
  }, [effective.accentHex, effective.accent]);
  const hex = normalizeHex(draft);
  const check = hex ? checkAccent(hex) : null;
  const apply = (value: string) => {
    const next = normalizeHex(value);
    setDraft(value);
    if (next) setAccentHex(next);
  };
  return (
    <div className="grid gap-2 sm:grid-cols-[9rem_1fr] sm:items-start">
      <span className="pt-2 text-sm font-medium text-content-primary">
        {t('settings.style_custom_colour', { defaultValue: 'Company colour' })}
      </span>
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="color"
            value={hex ?? '#000000'}
            onChange={(e) => apply(e.target.value)}
            aria-label={t('settings.style_custom_colour', { defaultValue: 'Company colour' })}
            className={`h-9 w-11 cursor-pointer rounded-lg border-2 bg-transparent p-0.5 ${
              effective.accentHex ? 'border-oe-blue' : 'border-border-light'
            }`}
          />
          <input
            value={draft}
            onChange={(e) => apply(e.target.value)}
            maxLength={7}
            spellCheck={false}
            aria-label={t('settings.style_custom_hex', { defaultValue: 'Hex code' })}
            aria-invalid={!hex}
            className="h-9 w-28 rounded-lg border border-border bg-surface-primary px-2 font-mono text-sm uppercase text-content-primary"
          />
          {check && (
            <span
              className={`inline-flex h-7 items-center rounded-md px-2 text-xs font-semibold text-white`}
              style={{ background: hex ?? undefined }}
            >
              {t('settings.style_custom_sample', { defaultValue: 'Button' })}
            </span>
          )}
        </div>
        {check && !check.passesAA && (
          <p className="text-xs text-semantic-warning" role="status">
            {t('settings.style_custom_low_contrast', {
              defaultValue: 'White text on this colour is hard to read ({{ratio}}:1, needs 4.5:1).',
              ratio: check.ratio.toFixed(1),
            })}{' '}
            <button
              type="button"
              className="font-medium underline"
              onClick={() => apply(check.accessible)}
            >
              {t('settings.style_custom_use_accessible', {
                defaultValue: 'Use {{hex}} instead',
                hex: check.accessible.toUpperCase(),
              })}
            </button>
          </p>
        )}
        <p className="text-xs text-content-tertiary">
          {t('settings.style_custom_hint', {
            defaultValue: 'Hover, pressed and dark mode shades are worked out from it.',
          })}
        </p>
      </div>
    </div>
  );
}

export function AppearanceStyleCard() {
  const { t } = useTranslation();
  const fontLabel = useFontLabel();
  const effective = useAppearanceStore((s) => s.effective);
  const user = useAppearanceStore((s) => s.user);
  const workspace = useAppearanceStore((s) => s.workspace);
  const setAppearance = useAppearanceStore((s) => s.setAppearance);
  const setAxis = useAppearanceStore((s) => s.setAxis);
  const followWorkspace = useAppearanceStore((s) => s.followWorkspace);
  const setWorkspaceDefault = useAppearanceStore((s) => s.setWorkspaceDefault);
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';
  const [saving, setSaving] = useState(false);
  const [comfort, setComfortState] = useState<Comfort>(readComfort);
  const setComfort = (next: Comfort) => {
    writeComfort(next);
    setComfortState(next);
  };
  const comfortChanged = comfort.motion !== DEFAULT_COMFORT.motion || comfort.contrast !== DEFAULT_COMFORT.contrast;
  const resetAll = () => {
    followWorkspace();
    setComfort({ ...DEFAULT_COMFORT });
  };

  // Previews draw each style in its own font, so fetch those few stylesheets.
  useEffect(() => {
    for (const font of FONTS) ensureFontLoaded(font);
  }, []);

  const current = matchPreset(effective);
  const presetName = (id: AppearancePreset['id']) =>
    t(`settings.style_preset_${id}`, { defaultValue: id.charAt(0).toUpperCase() + id.slice(1) });

  const source = user
    ? t('settings.style_source_personal', { defaultValue: 'Your own style, saved on this device.' })
    : workspace
      ? t('settings.style_source_workspace', { defaultValue: 'Following the workspace default.' })
      : t('settings.style_source_platform', { defaultValue: 'Platform default.' });

  const saveWorkspace = async (value: Appearance | null) => {
    setSaving(true);
    try {
      // Axis by axis, so the workspace menu look saved beside it is kept.
      // Text size is personal: the workspace payload does not carry it.
      const { accentHex, text: _text, ...axes } = value ?? ({} as Partial<Appearance>);
      await apiPut('/v1/branding/', {
        appearance: value
          ? { ...axes, accent_hex: accentHex ?? null }
          : { accent: null, font: null, density: null, radius: null, accent_hex: null },
      });
      setWorkspaceDefault(value);
      useToastStore.getState().addToast({
        type: 'success',
        title: value
          ? t('settings.style_workspace_saved', { defaultValue: 'Workspace default saved' })
          : t('settings.style_workspace_cleared', { defaultValue: 'Workspace default cleared' }),
      });
    } catch {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('settings.style_workspace_failed', { defaultValue: 'Could not save the workspace default' }),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title={t('settings.style_title', { defaultValue: 'Style' })}
        subtitle={t('settings.style_subtitle', {
          defaultValue: 'Colours, font, spacing and corners. Pick a ready style or tune each part below.',
        })}
      />
      <CardContent>
        <div
          role="radiogroup"
          aria-label={t('settings.style_title', { defaultValue: 'Style' })}
          className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] items-stretch gap-2"
        >
          {APPEARANCE_PRESETS.map((preset) => {
            const active = current === preset.id;
            return (
              <button
                key={preset.id}
                type="button"
                role="radio"
                aria-checked={active}
                aria-label={presetName(preset.id)}
                onClick={() => setAppearance({ ...preset.value, text: effective.text })}
                className={`block h-full w-full rounded-xl border-2 p-1.5 text-start transition-colors duration-normal ease-oe ${
                  active ? 'border-oe-blue bg-oe-blue-subtle' : 'border-transparent hover:border-border'
                }`}
              >
                <StylePreview value={preset.value} label={presetName(preset.id)} active={active} />
              </button>
            );
          })}
          <div
            role="radio"
            aria-checked={current === null}
            aria-disabled={current !== null}
            className={`h-full rounded-xl border-2 border-dashed p-1.5 ${
              current === null ? 'border-oe-blue bg-oe-blue-subtle' : 'border-border-light opacity-60'
            }`}
          >
            <StylePreview
              value={effective}
              label={t('settings.style_custom', { defaultValue: 'Custom' })}
              active={current === null}
            />
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-3 border-t border-border-light pt-4">
          <OptionRow label={t('settings.style_accent', { defaultValue: 'Accent colour' })}>
            {ACCENTS.map((accent) => (
              <Choice
                key={accent}
                active={!effective.accentHex && effective.accent === accent}
                onSelect={() => setAxis('accent', accent)}
                label={t(`settings.style_accent_${accent}`, { defaultValue: accent })}
              >
                <span className="h-3.5 w-3.5 rounded-full" style={{ background: ACCENT_SWATCH[accent] }} />
                {t(`settings.style_accent_${accent}`, { defaultValue: accent })}
              </Choice>
            ))}
          </OptionRow>
          <CustomColourRow />
          <OptionRow label={t('settings.style_font', { defaultValue: 'Font' })}>
            {FONTS.map((font) => (
              <Choice
                key={font}
                active={effective.font === font}
                onSelect={() => setAxis('font', font)}
                label={fontLabel(font)}
                style={{ fontFamily: FONT_STACK[font] }}
              />
            ))}
          </OptionRow>
          <OptionRow label={t('settings.style_density', { defaultValue: 'Density' })}>
            {DENSITIES.map((density) => (
              <Choice
                key={density}
                active={effective.density === density}
                onSelect={() => setAxis('density', density)}
                label={t(`settings.style_density_${density}`, { defaultValue: density })}
              />
            ))}
          </OptionRow>
          <OptionRow label={t('settings.style_radius', { defaultValue: 'Corners' })}>
            {RADII.map((radius) => (
              <Choice
                key={radius}
                active={effective.radius === radius}
                onSelect={() => setAxis('radius', radius)}
                label={t(`settings.style_radius_${radius}`, { defaultValue: radius })}
              />
            ))}
          </OptionRow>
          <OptionRow label={t('settings.style_text', { defaultValue: 'Text size' })}>
            {TEXT_SIZES.map((size) => (
              <Choice
                key={size}
                active={effective.text === size}
                onSelect={() => setAxis('text', size)}
                label={t(`settings.style_text_${size}`, { defaultValue: TEXT_LABEL[size] })}
              >
                <span aria-hidden="true" style={{ fontSize: `${15 * TEXT_SCALE[size]}px`, lineHeight: 1 }}>
                  Aa
                </span>
              </Choice>
            ))}
          </OptionRow>
          <p
            className="rounded-lg bg-surface-secondary/50 px-3 py-2 text-content-secondary"
            style={{ fontSize: `${15 * TEXT_SCALE[effective.text]}px` }}
          >
            {t('settings.style_text_preview', { defaultValue: 'The quick brown fox: 1,250.00 m3 of concrete, C30/37.' })}
          </p>
          <OptionRow label={t('settings.style_motion', { defaultValue: 'Motion' })}>
            {MOTIONS.map((motion) => (
              <Choice
                key={motion}
                active={comfort.motion === motion}
                onSelect={() => setComfort({ ...comfort, motion })}
                label={t(`settings.style_motion_${motion}`, { defaultValue: motion })}
              />
            ))}
          </OptionRow>
          <OptionRow label={t('settings.style_contrast', { defaultValue: 'Contrast' })}>
            {CONTRASTS.map((contrast) => (
              <Choice
                key={contrast}
                active={comfort.contrast === contrast}
                onSelect={() => setComfort({ ...comfort, contrast })}
                label={t(`settings.style_contrast_${contrast}`, { defaultValue: contrast })}
              />
            ))}
          </OptionRow>
          <p className="text-xs text-content-tertiary">
            {t('settings.style_font_hint', {
              defaultValue: 'Arabic, Hebrew, Asian and Indic scripts always use the system font.',
            })}
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border-light pt-4">
          <p className="text-xs text-content-secondary">{source}</p>
          {(user || comfortChanged) && (
            <Button variant="secondary" size="sm" onClick={resetAll}>
              {workspace
                ? t('settings.style_use_workspace', { defaultValue: 'Use workspace default' })
                : t('settings.style_reset', { defaultValue: 'Reset to default' })}
            </Button>
          )}
        </div>

        {isAdmin && (
          <div className="mt-4 rounded-lg border border-border-light bg-surface-secondary/50 p-3">
            <p className="text-sm font-medium text-content-primary">
              {t('settings.style_workspace_title', { defaultValue: 'Workspace default' })}
            </p>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('settings.style_workspace_desc', {
                defaultValue:
                  'Make the style shown above the default for everyone in this workspace. People who picked their own style keep it.',
              })}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" disabled={saving} onClick={() => void saveWorkspace(effective)}>
                {t('settings.style_workspace_save', { defaultValue: 'Set as workspace default' })}
              </Button>
              {workspace && (
                <Button variant="ghost" size="sm" disabled={saving} onClick={() => void saveWorkspace(null)}>
                  {t('settings.style_workspace_clear', { defaultValue: 'Clear workspace default' })}
                </Button>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
