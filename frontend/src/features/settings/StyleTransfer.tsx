// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Share a style: download it as a small JSON file, load one, or copy a link
 * (`/settings?appearance=<code>`). Whatever comes in is validated and shown in
 * a confirm dialog before anything changes.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Link2, Upload } from 'lucide-react';
import { Button, ConfirmDialog } from '@/shared/ui';
import { matchPreset } from '@/shared/lib/appearance';
import {
  STYLE_MAX_BYTES,
  STYLE_URL_PARAM,
  decodeStyleCode,
  parseStyle,
  styleShareUrl,
  styleToJson,
  type SharedStyle,
  type StyleParseError,
} from '@/shared/lib/styleShare';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { useToastStore } from '@/stores/useToastStore';

export function applySharedStyle(style: SharedStyle): void {
  useAppearanceStore.getState().setAppearance(style.appearance);
  const theme = useThemeStore.getState();
  if (style.schedule) theme.setSchedule(style.schedule);
  if (style.theme) theme.setTheme(style.theme);
}

export function StyleTransfer() {
  const { t } = useTranslation();
  const effective = useAppearanceStore((s) => s.effective);
  const theme = useThemeStore((s) => s.theme);
  const schedule = useThemeStore((s) => s.schedule);
  const [pending, setPending] = useState<SharedStyle | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const toast = useToastStore.getState().addToast;

  const current: SharedStyle = { appearance: effective, theme, ...(theme === 'schedule' ? { schedule } : {}) };

  const errorText = (e: StyleParseError) =>
    ({
      too_large: t('settings.style_import_err_too_large', { defaultValue: 'The file is too large to be a style.' }),
      not_json: t('settings.style_import_err_not_json', { defaultValue: 'This is not a style file or link.' }),
      wrong_format: t('settings.style_import_err_not_json', { defaultValue: 'This is not a style file or link.' }),
      wrong_version: t('settings.style_import_err_version', {
        defaultValue: 'This style was made by a newer version of the app.',
      }),
      empty: t('settings.style_import_err_empty', { defaultValue: 'The style holds no setting this app knows.' }),
    })[e];

  const fail = (e: StyleParseError) =>
    toast({
      type: 'error',
      title: t('settings.style_import_failed', { defaultValue: 'Could not load the style' }),
      message: errorText(e),
    });

  // A shared link opens Settings with the style in the query: ask, then drop it from the URL.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get(STYLE_URL_PARAM);
    if (!code) return;
    params.delete(STYLE_URL_PARAM);
    const qs = params.toString();
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${qs ? `?${qs}` : ''}`);
    const r = decodeStyleCode(code);
    if (r.ok) setPending(r.style);
    else fail(r.error);
    // Runs once on arrival; `fail` only reads translations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const download = () => {
    const blob = new Blob([styleToJson(current)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'style.oestyle.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyLink = async () => {
    const link = styleShareUrl(current, window.location.origin);
    try {
      await navigator.clipboard.writeText(link);
      toast({ type: 'success', title: t('settings.style_link_copied', { defaultValue: 'Link copied' }) });
    } catch {
      toast({
        type: 'error',
        title: t('settings.style_link_failed', { defaultValue: 'Could not copy the link' }),
        message: link,
      });
    }
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > STYLE_MAX_BYTES) return fail('too_large');
    const r = parseStyle(await file.text());
    if (r.ok) setPending(r.style);
    else fail(r.error);
  };

  const summary = (s: SharedStyle) => {
    const preset = matchPreset(s.appearance, s.theme);
    const name = preset
      ? t(`settings.style_preset_${preset}`, { defaultValue: preset })
      : t('settings.style_custom', { defaultValue: 'Custom' });
    const themeName = s.theme ? t(`settings.theme_${s.theme}`, { defaultValue: s.theme }) : null;
    return t('settings.style_import_confirm_body', {
      defaultValue: 'Apply the style "{{name}}" to your screen? It replaces your current style{{theme}}.',
      name,
      theme: themeName ? ` (${themeName})` : '',
    });
  };

  return (
    <div className="mt-4 border-t border-border-light pt-4">
      <p className="text-sm font-medium text-content-primary">
        {t('settings.style_share_title', { defaultValue: 'Share this style' })}
      </p>
      <p className="mt-0.5 text-xs text-content-tertiary">
        {t('settings.style_share_desc', {
          defaultValue: 'Save it as a file or send a link, so a colleague gets the same look in one click.',
        })}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" onClick={download} icon={<Download size={14} />}>
          {t('settings.style_export', { defaultValue: 'Download style' })}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => fileRef.current?.click()} icon={<Upload size={14} />}>
          {t('settings.style_import', { defaultValue: 'Load style file' })}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => void copyLink()} icon={<Link2 size={14} />}>
          {t('settings.style_copy_link', { defaultValue: 'Copy link' })}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          aria-label={t('settings.style_import', { defaultValue: 'Load style file' })}
          onChange={(e) => {
            void onFile(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
      </div>
      <ConfirmDialog
        open={pending !== null}
        variant="warning"
        title={t('settings.style_import_confirm_title', { defaultValue: 'Apply this style?' })}
        message={pending ? summary(pending) : ''}
        confirmLabel={t('settings.style_import_apply', { defaultValue: 'Apply' })}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) applySharedStyle(pending);
          setPending(null);
        }}
      />
    </div>
  );
}
