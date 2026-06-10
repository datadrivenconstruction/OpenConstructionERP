// White-label branding for the sidebar header.
//
// Renders the user's company logo / name when they have customised
// the platform via the edit modal; otherwise renders the default
// OpenConstructionERP wordmark. Clicking the brand area (or the
// "Customise" pencil that appears on hover) opens the editor.
//
// Layout rules:
//   * No customisation → full OpenConstructionERP logo+wordmark, as
//     before (visual parity with v3.0.5).
//   * Logo set        → user's logo fills the header width;
//                       "OpenConstructionERP" subtitle is rendered at
//                       roughly 1/3 of the original size beneath it
//                       as a "powered by" attribution (required by
//                       the AGPL-3.0 licence).
//   * Name only       → company name in Plus Jakarta Sans 800, sized
//                       to match the default wordmark; same small
//                       OpenConstructionERP subtitle below.
//
// The editor is a lightweight inline form (not WideModal) so the
// sidebar can keep working on narrow viewports. The logo upload
// reads the file as a base64 data URL so we do not need a backend
// endpoint — branding lives entirely in localStorage and survives
// reload without server state.
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import clsx from 'clsx';
import { Pencil, Upload, Trash2, X, Building2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Logo } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  useBrandingStore,
  BRANDING_MAX_LOGO_BYTES,
} from '@/stores/useBrandingStore';

interface CustomBrandingProps {
  /** When true (icon-only sidebar), render a compact logo without text. */
  iconified: boolean;
}

const MAX_NAME_LEN = 60;
const ACCEPTED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/svg+xml', 'image/webp'];

/** Read a File into a base64 data URL, with size + mime gating. */
async function fileToDataUrl(file: File): Promise<string> {
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
    throw new Error('Unsupported image type. Use PNG, JPG, SVG, or WebP.');
  }
  if (file.size > BRANDING_MAX_LOGO_BYTES) {
    throw new Error(
      `Logo too large (${Math.round(file.size / 1024)} KB). Max ${Math.round(
        BRANDING_MAX_LOGO_BYTES / 1024,
      )} KB.`,
    );
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Read failed'));
    reader.onload = () => {
      const v = reader.result;
      if (typeof v !== 'string') {
        reject(new Error('Read produced non-string'));
        return;
      }
      resolve(v);
    };
    reader.readAsDataURL(file);
  });
}

export function CustomBranding({ iconified }: CustomBrandingProps) {
  const { t } = useTranslation();
  const { mode, logoDataUrl, companyName } = useBrandingStore();
  const [editing, setEditing] = useState(false);

  // Iconified sidebar — render only the brand glyph (user logo if set,
  // otherwise the OE logo). No subtitle / company name in this mode.
  if (iconified) {
    if (mode === 'logo' && logoDataUrl) {
      return (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="hover:opacity-80 transition-opacity"
          title={companyName || t('branding.edit', { defaultValue: 'Customise branding' })}
          aria-label={t('branding.edit', { defaultValue: 'Customise branding' })}
        >
          <img
            src={logoDataUrl}
            alt={companyName || 'Custom logo'}
            className="h-7 w-7 object-contain rounded"
            draggable={false}
          />
        </button>
      );
    }
    return (
      <a
        href="https://openconstructionerp.com/?utm_source=app"
        target="_blank"
        rel="noopener noreferrer"
        className="hover:opacity-80 transition-opacity"
        title="OpenConstructionERP"
      >
        <Logo size="sm" />
      </a>
    );
  }

  // Expanded sidebar — brand on the left (max width), persistent
  // edit button on the right (fixed 36px so it never crowds the
  // wordmark). The edit button is always visible, not hover-revealed,
  // per user request — discoverability of white-labelling matters.
  const customised = mode === 'logo' || mode === 'text';

  return (
    <>
      <div className="flex w-full items-center gap-1.5">
        {/* LEFT — brand area (grows to fill). Clicking opens the
            editor; whole block is a click target. `min-w-0` lets
            flex truncate long company names cleanly. */}
        <div className="flex-1 min-w-0">
          {customised ? (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="block w-full text-left rounded-lg p-1 -m-1 hover:bg-surface-secondary/40 transition-colors"
              aria-label={t('branding.edit', { defaultValue: 'Customise branding' })}
              title={t('branding.edit', { defaultValue: 'Customise branding' })}
            >
              {mode === 'logo' && logoDataUrl ? (
                <img
                  src={logoDataUrl}
                  alt={companyName || 'Custom logo'}
                  className="block max-h-[40px] w-auto max-w-full object-contain"
                  draggable={false}
                />
              ) : (
                <span
                  className="block truncate text-[17px] font-extrabold text-content-primary leading-none"
                  style={{
                    fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
                    letterSpacing: '-0.02em',
                  }}
                  title={companyName}
                >
                  {companyName}
                </span>
              )}
              {/* "by OpenConstructionERP" — minimal subordinate attribution
                  under the user's brand. AGPL-3.0 attribution requirement
                  is satisfied while the user's logo stays the dominant
                  visual; font is small + muted on purpose. */}
              <span
                className="mt-1 block text-[8px] leading-none text-content-quaternary truncate"
                style={{
                  fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
                  letterSpacing: '0.03em',
                }}
              >
                by{' '}
                <span className="font-semibold tracking-tight">
                  Open<span className="text-oe-blue/60">Construction</span>
                  <span className="text-content-quaternary">ERP</span>
                </span>
              </span>
            </button>
          ) : (
            <a
              href="https://openconstructionerp.com/?utm_source=app"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 hover:opacity-80 transition-opacity"
              title="OpenConstructionERP"
            >
              {/* Compact wordmark — 13px text + smaller gap to fit
                  the 248px sidebar minus the 32px edit button without
                  visual crowding. Standard LogoWithText size="xs" used
                  15px and clipped against the pencil. */}
              <Logo size="xs" />
              <span
                className="text-[13px] font-medium text-content-primary whitespace-nowrap leading-none"
                style={{
                  fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
                  letterSpacing: '-0.02em',
                }}
              >
                Open<span className="text-oe-blue">Construction</span>
                <span className="text-content-quaternary">ERP</span>
              </span>
            </a>
          )}
        </div>

        {/* RIGHT — always-visible edit button (36px square so it
            doesn't crowd the wordmark). User asked for it to be
            permanent (not hover-only) so discoverability of the
            white-labelling feature is high. */}
        <button
          type="button"
          onClick={() => setEditing(true)}
          className={clsx(
            'shrink-0 h-8 w-8 flex items-center justify-center rounded-lg',
            'border border-border-light bg-surface-secondary/30',
            'text-content-tertiary hover:text-oe-blue',
            'hover:border-oe-blue/40 hover:bg-oe-blue/5',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
            'transition-colors',
          )}
          aria-label={t('branding.edit', { defaultValue: 'Customise branding' })}
          title={t('branding.edit_tooltip', {
            defaultValue: 'Add your logo or company name',
          })}
        >
          <Pencil size={13} strokeWidth={2.25} />
        </button>
      </div>

      {editing && <BrandingEditorModal onClose={() => setEditing(false)} />}
    </>
  );
}

/**
 * Store-wired branding editor modal. Self-contained: pulls the branding
 * store + toast store itself and renders {@link BrandingEditor} with all
 * callbacks bound. Reused verbatim by the sidebar brand control *and* the
 * pre-auth login screen so "customise logo" behaves identically in both
 * places (single source of truth — no duplicated upload/validation).
 */
export function BrandingEditorModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { mode, logoDataUrl, companyName, setLogo, setCompanyName, reset } =
    useBrandingStore();
  const { addToast } = useToastStore();

  return (
    <BrandingEditor
      mode={mode}
      logoDataUrl={logoDataUrl}
      companyName={companyName}
      onClose={onClose}
      onApplyLogo={async (file) => {
        try {
          const url = await fileToDataUrl(file);
          setLogo(url);
          addToast({
            type: 'success',
            title: t('branding.logo_saved', { defaultValue: 'Logo updated' }),
          });
          onClose();
        } catch (e) {
          addToast({
            type: 'error',
            title: t('branding.logo_error', { defaultValue: 'Could not load logo' }),
            message: e instanceof Error ? e.message : String(e),
          });
        }
      }}
      onApplyName={(name) => {
        setCompanyName(name);
        addToast({
          type: 'success',
          title: t('branding.name_saved', { defaultValue: 'Company name updated' }),
        });
        onClose();
      }}
      onReset={() => {
        reset();
        addToast({
          type: 'info',
          title: t('branding.reset', { defaultValue: 'Restored default branding' }),
        });
        onClose();
      }}
    />
  );
}

/* ── Modal ───────────────────────────────────────────────────────────── */

interface EditorProps {
  mode: 'default' | 'logo' | 'text';
  logoDataUrl: string | null;
  companyName: string;
  onClose: () => void;
  onApplyLogo: (file: File) => void | Promise<void>;
  onApplyName: (name: string) => void;
  onReset: () => void;
}

function BrandingEditor({
  mode,
  logoDataUrl,
  companyName,
  onClose,
  onApplyLogo,
  onApplyName,
  onReset,
}: EditorProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'logo' | 'name'>(mode === 'text' ? 'name' : 'logo');
  const [nameDraft, setNameDraft] = useState(companyName);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Escape closes
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (tab === 'name') nameInputRef.current?.focus();
  }, [tab]);

  return createPortal(
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="branding-editor-heading"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl bg-surface-primary border border-border shadow-2xl shadow-black/30 overflow-hidden">
        <header className="flex items-center justify-between px-5 py-4 border-b border-border-light">
          <h2
            id="branding-editor-heading"
            className="text-base font-semibold text-content-primary"
          >
            {t('branding.title', { defaultValue: 'Customise branding' })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="h-7 w-7 flex items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            aria-label={t('common.close')}
          >
            <X size={16} />
          </button>
        </header>

        {/* Tab switch */}
        <div className="px-5 pt-4">
          <div
            role="tablist"
            className="inline-flex rounded-lg bg-surface-secondary p-1"
          >
            {(['logo', 'name'] as const).map((id) => (
              <button
                key={id}
                role="tab"
                type="button"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={clsx(
                  'px-3 py-1.5 text-sm rounded-md transition-colors',
                  tab === id
                    ? 'bg-surface-primary text-content-primary shadow-sm'
                    : 'text-content-secondary hover:text-content-primary',
                )}
              >
                {id === 'logo'
                  ? t('branding.tab_logo', { defaultValue: 'Logo' })
                  : t('branding.tab_name', { defaultValue: 'Company name' })}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="px-5 py-5">
          {tab === 'logo' ? (
            <div>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/svg+xml,image/webp"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void onApplyLogo(f);
                }}
              />
              <div
                role="button"
                tabIndex={0}
                onClick={() => fileRef.current?.click()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    fileRef.current?.click();
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
                  const f = e.dataTransfer.files?.[0];
                  if (f) void onApplyLogo(f);
                }}
                className={clsx(
                  'flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed py-10 px-4 cursor-pointer transition-colors',
                  dragging
                    ? 'border-oe-blue bg-oe-blue/5'
                    : 'border-border hover:border-oe-blue/60 hover:bg-surface-secondary/40',
                )}
              >
                <div className="h-12 w-12 rounded-xl bg-oe-blue/10 border border-oe-blue/20 flex items-center justify-center">
                  <Upload size={20} className="text-oe-blue" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-content-primary">
                    {t('branding.logo_drop', {
                      defaultValue: 'Drop your logo here, or click to browse',
                    })}
                  </p>
                  <p className="text-xs text-content-tertiary mt-1">
                    {t('branding.logo_hint', {
                      defaultValue: 'PNG, JPG, SVG, or WebP - up to 2 MB',
                    })}
                  </p>
                </div>
              </div>
              {logoDataUrl && (
                <div className="mt-4 flex items-center gap-3 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
                  <img
                    src={logoDataUrl}
                    alt="Current logo"
                    className="h-10 w-10 object-contain rounded"
                    draggable={false}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-content-secondary">
                      {t('branding.current_logo', {
                        defaultValue: 'Current logo',
                      })}
                    </p>
                    <p className="text-[11px] text-content-tertiary truncate">
                      {Math.round(logoDataUrl.length / 1024)} KB
                    </p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                onApplyName(nameDraft);
              }}
            >
              <label
                htmlFor="branding-company-name"
                className="block text-xs font-medium text-content-secondary mb-1.5"
              >
                {t('branding.name_label', {
                  defaultValue: 'Display name shown in the sidebar',
                })}
              </label>
              <div className="relative">
                <Building2
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
                />
                <input
                  ref={nameInputRef}
                  id="branding-company-name"
                  type="text"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value.slice(0, MAX_NAME_LEN))}
                  placeholder={t('branding.name_placeholder', {
                    defaultValue: 'Acme Construction GmbH',
                  })}
                  maxLength={MAX_NAME_LEN}
                  className="w-full pl-9 pr-3 py-2 rounded-lg bg-surface-secondary border border-border-light focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20 focus:outline-none text-sm text-content-primary placeholder:text-content-tertiary"
                />
              </div>
              <p className="text-[11px] text-content-tertiary mt-1.5">
                {nameDraft.length}/{MAX_NAME_LEN}
              </p>
              <button
                type="submit"
                disabled={nameDraft.trim() === companyName.trim()}
                className={clsx(
                  'mt-4 w-full px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                  nameDraft.trim() === companyName.trim()
                    ? 'bg-surface-secondary text-content-tertiary cursor-not-allowed'
                    : 'bg-oe-blue text-white hover:bg-oe-blue/90',
                )}
              >
                {t('branding.name_apply', { defaultValue: 'Save name' })}
              </button>
            </form>
          )}
        </div>

        {/* Footer — reset is destructive so keep it secondary */}
        {(mode === 'logo' || mode === 'text') && (
          <footer className="flex items-center justify-between px-5 py-3 border-t border-border-light bg-surface-secondary/20">
            <button
              type="button"
              onClick={onReset}
              className="inline-flex items-center gap-1.5 text-xs text-content-tertiary hover:text-error-content transition-colors"
            >
              <Trash2 size={13} />
              {t('branding.reset_action', {
                defaultValue: 'Restore default branding',
              })}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-content-secondary hover:text-content-primary transition-colors"
            >
              {t('common.done', { defaultValue: 'Done' })}
            </button>
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}
