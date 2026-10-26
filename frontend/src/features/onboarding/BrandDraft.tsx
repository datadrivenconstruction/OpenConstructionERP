// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Your company" block of the wizard's look step: company name and logo as a
// draft. The look step applies it through useBrandingStore, the same store and
// server path the sidebar editor and Settings > General use.

import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Building2, RefreshCw, Trash2, Upload } from 'lucide-react';
import { ACCEPTED_IMAGE_TYPES, fileToDataUrl } from '@/app/layout/CustomBranding';
import { isSvgDataUrl, rasteriseSvgToPng } from '@/features/settings/rasteriseSvg';
import { BRANDING_MAX_LOGO_BYTES } from '@/stores/useBrandingStore';

export interface BrandDraft {
  logo: string | null;
  /** PNG copy of an SVG logo, printed on PDFs. */
  png: string | null;
  name: string;
}

const MAX_NAME_LEN = 60;

export function BrandDraftSection({ draft, onChange }: { draft: BrandDraft; onChange: (next: BrandDraft) => void }) {
  const { t } = useTranslation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);

  const take = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
      setError(t('settings.brand_bad_type', { defaultValue: 'Use an SVG, PNG, WebP or JPEG file.' }));
      return;
    }
    if (file.size > BRANDING_MAX_LOGO_BYTES) {
      setError(t('settings.brand_too_big', { defaultValue: 'The file is larger than 2 MB.' }));
      return;
    }
    setReading(true);
    try {
      const logo = await fileToDataUrl(file);
      const png = isSvgDataUrl(logo) ? await rasteriseSvgToPng(logo).catch(() => null) : null;
      onChange({ ...draft, logo, png });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setReading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const pick = () => fileRef.current?.click();
  const title = t('onboarding.brand_section', { defaultValue: 'Your company' });

  return (
    <section aria-label={title} data-testid="onboarding-brand">
      <h3 className="mb-1 text-sm font-semibold text-content-primary">{title}</h3>
      <p className="mb-2 text-xs text-content-tertiary">
        {t('onboarding.brand_section_hint', {
          defaultValue: 'Shown at the top of the menu and on the sign-in page for everyone in this workspace. Optional.',
        })}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex min-w-0 flex-col gap-1">
          <span className="text-xs font-medium text-content-secondary">
            {t('settings.brand_company_name', { defaultValue: 'Company name' })}
          </span>
          <span className="relative">
            <Building2 size={14} className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
            <input
              value={draft.name}
              maxLength={MAX_NAME_LEN}
              onChange={(e) => onChange({ ...draft, name: e.target.value.slice(0, MAX_NAME_LEN) })}
              placeholder={t('branding.name_placeholder', { defaultValue: 'Acme Construction GmbH' })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary ps-8 pe-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
            />
          </span>
        </label>

        <div className="min-w-0">
          <span className="mb-1 block text-xs font-medium text-content-secondary">
            {t('branding.tab_logo', { defaultValue: 'Logo' })}
          </span>
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPTED_IMAGE_TYPES.join(',')}
            className="hidden"
            data-testid="onboarding-brand-file"
            onChange={(e) => void take(e.target.files?.[0])}
          />
          {draft.logo ? (
            <div className="flex h-9 items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-2">
              <img
                src={draft.logo}
                alt={t('branding.current_logo', { defaultValue: 'Current logo' })}
                className="h-6 max-w-[96px] object-contain"
                draggable={false}
              />
              <span className="flex-1" />
              <button
                type="button"
                onClick={pick}
                className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-content-secondary hover:text-oe-blue"
              >
                <RefreshCw size={12} />
                {t('onboarding.brand_replace', { defaultValue: 'Replace' })}
              </button>
              <button
                type="button"
                onClick={() => onChange({ ...draft, logo: null, png: null })}
                className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-content-secondary hover:text-error-content"
              >
                <Trash2 size={12} />
                {t('settings.brand_remove', { defaultValue: 'Remove' })}
              </button>
            </div>
          ) : (
            <div
              role="button"
              tabIndex={0}
              aria-busy={reading}
              data-testid="onboarding-brand-drop"
              onClick={pick}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  pick();
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                void take(e.dataTransfer.files?.[0]);
              }}
              className={`flex min-h-9 cursor-pointer items-center gap-2 rounded-lg border-2 border-dashed px-2.5 py-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 ${
                dragging ? 'border-oe-blue bg-oe-blue/5' : 'border-border hover:border-oe-blue/60'
              }`}
            >
              <Upload size={14} className="shrink-0 text-oe-blue" />
              <span className="min-w-0">
                <span className="block truncate text-xs font-medium text-content-primary">
                  {t('branding.logo_drop', { defaultValue: 'Drop your logo here, or click to browse' })}
                </span>
                <span className="block truncate text-[11px] text-content-tertiary">
                  {t('branding.logo_hint', { defaultValue: 'PNG, JPG, SVG, or WebP - up to 2 MB' })}
                </span>
              </span>
            </div>
          )}
          {error && (
            <p role="alert" className="mt-1 text-xs text-error-content">
              {error}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
