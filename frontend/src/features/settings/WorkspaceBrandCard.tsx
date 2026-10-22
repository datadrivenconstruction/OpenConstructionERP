// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Workspace logo" card in Settings > General. Same storage and server path as
 * the editor behind the button next to the sidebar logo (useBrandingStore,
 * PUT /v1/branding/); this card adds the dark-mode variant, whether that edit
 * button is shown, and whether the company name sits next to the logo.
 * Admins change it; everyone else sees the current logo read-only.
 */
import { useId, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, Trash2 } from 'lucide-react';
import { Card, CardHeader, CardContent, Button } from '@/shared/ui';
import { apiPut } from '@/shared/lib/api';
import { ACCEPTED_IMAGE_TYPES, fileToDataUrl } from '@/app/layout/CustomBranding';
import { BRANDING_MAX_LOGO_BYTES, useBrandingStore } from '@/stores/useBrandingStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { isSvgDataUrl, rasteriseSvgToPng } from './rasteriseSvg';

/** Logo types offered here; the server enforces the same list. */
export const LOGO_TYPES = ACCEPTED_IMAGE_TYPES;

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <span id={id} className="text-sm font-medium text-content-primary">
          {label}
        </span>
        {hint && <p className="mt-0.5 text-xs text-content-tertiary">{hint}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={id}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
          checked ? 'bg-oe-blue' : 'bg-border'
        }`}
      >
        <span
          className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-[18px]' : 'translate-x-0.5'
          }`}
        />
      </button>
    </div>
  );
}

function LogoSlot({
  label,
  src,
  dark,
  canEdit,
  busy,
  onPick,
  onClear,
}: {
  label: string;
  src: string | null;
  dark?: boolean;
  canEdit: boolean;
  busy: boolean;
  onPick: (file: File) => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium text-content-secondary">{label}</span>
      <div
        className={`flex h-20 items-center justify-center rounded-lg border border-border-light p-3 ${
          dark ? 'bg-slate-900' : 'bg-white'
        }`}
      >
        {src ? (
          <img src={src} alt={label} className="max-h-full max-w-full object-contain" draggable={false} />
        ) : (
          <span className={`text-xs ${dark ? 'text-slate-400' : 'text-content-tertiary'}`}>
            {t('settings.brand_no_logo', { defaultValue: 'Default logo' })}
          </span>
        )}
      </div>
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <input
            ref={input}
            type="file"
            accept={LOGO_TYPES.join(',')}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (file) onPick(file);
            }}
          />
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => input.current?.click()}>
            <Upload size={14} />
            {t('settings.brand_upload', { defaultValue: 'Upload' })}
          </Button>
          {src && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={onClear}>
              <Trash2 size={14} />
              {t('settings.brand_remove', { defaultValue: 'Remove' })}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export function WorkspaceBrandCard() {
  const { t } = useTranslation();
  const { logoDataUrl, companyName, options, setLogo, setCompanyName, reset, persistToServer, setOptions } =
    useBrandingStore();
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState(companyName);
  const toast = useToastStore.getState().addToast;

  const fail = (e: unknown) =>
    toast({
      type: 'error',
      title: t('settings.brand_failed', { defaultValue: 'Could not save the logo' }),
      message: serverMessage(e),
    });

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
      toast({ type: 'success', title: t('settings.brand_saved', { defaultValue: 'Workspace logo saved' }) });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const readLogo = async (file: File) => {
    if (!LOGO_TYPES.includes(file.type)) {
      throw new Error(t('settings.brand_bad_type', { defaultValue: 'Use an SVG, PNG, WebP or JPEG file.' }));
    }
    if (file.size > BRANDING_MAX_LOGO_BYTES) {
      throw new Error(t('settings.brand_too_big', { defaultValue: 'The file is larger than 2 MB.' }));
    }
    return fileToDataUrl(file);
  };

  const saveOptions = (patch: Record<string, unknown>) =>
    run(async () => {
      setOptions(await apiPut('/v1/branding/', patch));
    });

  return (
    <Card>
      <CardHeader
        title={t('settings.brand_title', { defaultValue: 'Workspace logo' })}
        subtitle={t('settings.brand_subtitle', {
          defaultValue: 'Your company logo in the menu and on the sign-in page, for everyone in this workspace.',
        })}
      />
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2">
          <LogoSlot
            label={t('settings.brand_logo_light', { defaultValue: 'Logo' })}
            src={logoDataUrl}
            canEdit={isAdmin}
            busy={busy}
            onPick={(file) =>
              void run(async () => {
                const url = await readLogo(file);
                const png = isSvgDataUrl(url) ? await rasteriseSvgToPng(url).catch(() => null) : null;
                const previous = { logo: logoDataUrl };
                setLogo(url, png);
                if (!(await persistToServer())) {
                  setLogo(previous.logo);
                  throw new Error(t('settings.brand_rejected', { defaultValue: 'The server did not accept this file.' }));
                }
              })
            }
            onClear={() =>
              void run(async () => {
                setLogo(null);
                await persistToServer();
                // The server drops the dark variant with the main logo.
                await useBrandingStore.getState().hydrateFromServer();
              })
            }
          />
          <LogoSlot
            label={t('settings.brand_logo_dark', { defaultValue: 'Dark mode logo (optional)' })}
            src={options.logoDarkDataUrl}
            dark
            canEdit={isAdmin && !!logoDataUrl}
            busy={busy}
            onPick={(file) =>
              void readLogo(file).then((url) => saveOptions({ logo_dark_data_url: url }), fail)
            }
            onClear={() => void saveOptions({ logo_dark_data_url: null })}
          />
        </div>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('settings.brand_rules', {
            defaultValue: 'SVG, PNG, WebP or JPEG, up to 2 MB. Scripts and external links are removed from SVG files.',
          })}
        </p>

        {isAdmin ? (
          <div className="mt-4 flex flex-col gap-4 border-t border-border-light pt-4">
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-sm font-medium text-content-primary">
                  {t('settings.brand_company_name', { defaultValue: 'Company name' })}
                </span>
                <input
                  value={name}
                  maxLength={60}
                  onChange={(e) => setName(e.target.value)}
                  className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary"
                />
              </label>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy || name.trim() === companyName}
                onClick={() =>
                  void run(async () => {
                    setCompanyName(name);
                    await persistToServer();
                  })
                }
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
            <Toggle
              checked={options.showCompanyName}
              disabled={busy}
              onChange={(v) => void saveOptions({ show_company_name: v })}
              label={t('settings.brand_show_name', { defaultValue: 'Show company name next to the logo' })}
            />
            <Toggle
              checked={options.showLogoEdit}
              disabled={busy}
              onChange={(v) => void saveOptions({ show_logo_edit: v })}
              label={t('settings.brand_show_edit', { defaultValue: 'Edit button next to the logo' })}
              hint={t('settings.brand_show_edit_hint', {
                defaultValue: 'Quick access to change the logo from the menu. Only admins ever see it.',
              })}
            />
            {(logoDataUrl || companyName) && (
              <div>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      reset();
                      setName('');
                      await persistToServer();
                      setOptions(await apiPut('/v1/branding/', { logo_dark_data_url: null }));
                    })
                  }
                >
                  {t('settings.brand_reset', { defaultValue: 'Back to the default logo' })}
                </Button>
              </div>
            )}
          </div>
        ) : (
          <p className="mt-4 border-t border-border-light pt-4 text-xs text-content-tertiary">
            {t('settings.brand_admin_only', { defaultValue: 'Only an administrator can change the workspace logo.' })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function serverMessage(e: unknown): string | undefined {
  if (e && typeof e === 'object' && 'body' in e) {
    const detail = (e as { body?: { detail?: { message?: string } } }).body?.detail;
    if (detail?.message) return detail.message;
  }
  return e instanceof Error ? e.message : undefined;
}
