// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Custom branding for the sidebar header.
 *
 * Lets users white-label the in-app sidebar with their own company
 * logo (PNG/JPG/SVG) or company name. When set, the user's brand
 * shows prominently at the top of the sidebar; the
 * "OpenConstructionERP" wordmark moves below it at one-third the
 * size as a "powered by" attribution — still visible (we ship under
 * AGPL-3.0 with attribution requirements) but no longer the main
 * brand on the page.
 *
 * Persistence has two layers:
 *   - localStorage, for an instant first paint and offline / desktop use;
 *   - the server (GET/PUT/DELETE /api/v1/branding/), which is the source of
 *     truth so the brand follows the workspace to other browsers and to
 *     invited users who have not signed in yet (issue #272).
 * The logo is stored as a base64 data URL (size-capped at 2 MB to keep
 * localStorage healthy).
 */
import { create } from 'zustand';
import { apiGet, apiPut } from '@/shared/lib/api';
import { useAppearanceStore } from './useAppearanceStore';

const STORAGE_KEY = 'oe_custom_branding_v1';
const MAX_LOGO_BYTES = 2 * 1024 * 1024; // 2 MB cap on base64 payload

export type BrandingMode = 'default' | 'logo' | 'text';

/** Workspace-only branding options; set by an admin, read from the server. */
export interface BrandingOptions {
  /** Logo variant drawn in dark mode, or null to use the main logo. */
  logoDarkDataUrl: string | null;
  /** Show the quick edit button beside the sidebar logo (to admins). */
  showLogoEdit: boolean;
  /** Write the company name next to an uploaded logo. */
  showCompanyName: boolean;
}

const OPTIONS_KEY = 'oe_branding_options_v1';
const DEFAULT_OPTIONS: BrandingOptions = { logoDarkDataUrl: null, showLogoEdit: true, showCompanyName: false };

function sanitizeOptions(raw: unknown): BrandingOptions {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const dark = r.logoDarkDataUrl ?? r.logo_dark_data_url;
  return {
    logoDarkDataUrl: typeof dark === 'string' && dark.startsWith('data:image/') ? dark : null,
    showLogoEdit: (r.showLogoEdit ?? r.show_logo_edit) !== false,
    showCompanyName: (r.showCompanyName ?? r.show_company_name) === true,
  };
}

/**
 * The quick edit button beside the sidebar logo goes off once a logo first
 * appears, so the menu shows a clean brand; Settings > General switches it
 * back on, and a later replacement leaves that choice alone.
 */
export function logoEditAfterLogoChange(
  previousLogo: string | null,
  nextLogo: string | null,
  showLogoEdit: boolean,
): boolean {
  return !previousLogo && nextLogo ? false : showLogoEdit;
}

function loadOptions(): BrandingOptions {
  try {
    return sanitizeOptions(JSON.parse(localStorage.getItem(OPTIONS_KEY) || 'null'));
  } catch {
    return { ...DEFAULT_OPTIONS };
  }
}

function saveOptions(o: BrandingOptions): void {
  try {
    localStorage.setItem(OPTIONS_KEY, JSON.stringify(o));
  } catch {
    /* storage unavailable: options still apply for this session */
  }
}

export interface BrandingState {
  mode: BrandingMode;
  /** Base64 data URL of the uploaded logo (only valid when mode='logo'). */
  logoDataUrl: string | null;
  /** PNG copy of an SVG logo (made in the browser, printed on PDFs). */
  logoPngDataUrl: string | null;
  /** Company display text (only valid when mode='text'). */
  companyName: string;
  /**
   * Replace the user's logo. Pass `null` to clear (mode falls back
   * to whichever of `text` / `default` is appropriate).
   */
  setLogo: (dataUrl: string | null, pngDataUrl?: string | null) => void;
  /**
   * Set the company name and switch to `text` mode. Empty string
   * resets to `default`.
   */
  setCompanyName: (name: string) => void;
  /** Clear all customisation and return to the OpenConstructionERP brand. */
  reset: () => void;
  /**
   * Pull the workspace branding from the server and apply it (the server is the
   * source of truth, so it overrides the local cache). Best-effort: on any
   * failure the local cache is kept, so the desktop build and offline use keep
   * working. The endpoint is public, so this is safe to call before sign-in -
   * the login page does, so invited users see the workspace brand.
   */
  hydrateFromServer: () => Promise<void>;
  /** Workspace-only options (dark logo, edit button, name beside logo). */
  options: BrandingOptions;
  /** Apply options the server accepted (or that came back from it). */
  setOptions: (raw: unknown) => void;
  /**
   * Persist the current branding to the server so it follows the workspace to
   * every browser and to invited users. Admin only: a non-admin (or a pre-auth
   * caller) gets 403/401 which is swallowed, leaving the local change in place.
   * Returns true when the server accepted the change.
   */
  persistToServer: () => Promise<boolean>;
}

/** Server branding payload (snake_case mirrors the backend schema). */
interface ServerBranding {
  mode?: string;
  logo_data_url?: string | null;
  logo_png_data_url?: string | null;
  company_name?: string;
  logo_dark_data_url?: string | null;
  show_logo_edit?: boolean;
  show_company_name?: boolean;
  /** Workspace default UI appearance (style axes plus `menu`); see useAppearanceStore. */
  appearance?: { menu?: unknown } | null;
}

/** Coerce a server payload into a safe {@link Persisted} value. */
function fromServer(r: ServerBranding): Persisted {
  return {
    mode: r.mode === 'logo' || r.mode === 'text' ? r.mode : 'default',
    logoDataUrl:
      typeof r.logo_data_url === 'string' && r.logo_data_url.startsWith('data:image/')
        ? r.logo_data_url
        : null,
    logoPngDataUrl:
      typeof r.logo_png_data_url === 'string' && r.logo_png_data_url.startsWith('data:image/png')
        ? r.logo_png_data_url
        : null,
    companyName: typeof r.company_name === 'string' ? r.company_name.slice(0, 60) : '',
  };
}

interface Persisted {
  mode: BrandingMode;
  logoDataUrl: string | null;
  logoPngDataUrl: string | null;
  companyName: string;
}

function load(): Persisted {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { mode: 'default', logoDataUrl: null, logoPngDataUrl: null, companyName: '' };
    const parsed = JSON.parse(raw) as Partial<Persisted>;
    const mode: BrandingMode =
      parsed.mode === 'logo' || parsed.mode === 'text' ? parsed.mode : 'default';
    const logoDataUrl =
      typeof parsed.logoDataUrl === 'string' &&
      parsed.logoDataUrl.startsWith('data:image/') &&
      parsed.logoDataUrl.length < MAX_LOGO_BYTES * 2 // base64 expansion
        ? parsed.logoDataUrl
        : null;
    const logoPngDataUrl =
      logoDataUrl &&
      typeof parsed.logoPngDataUrl === 'string' &&
      parsed.logoPngDataUrl.startsWith('data:image/png')
        ? parsed.logoPngDataUrl
        : null;
    const companyName =
      typeof parsed.companyName === 'string' ? parsed.companyName.slice(0, 60) : '';
    return { mode, logoDataUrl, logoPngDataUrl, companyName };
  } catch {
    return { mode: 'default', logoDataUrl: null, logoPngDataUrl: null, companyName: '' };
  }
}

function save(s: Persisted) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    /* storage full or unavailable — silently drop, state stays in-memory */
  }
}

export const useBrandingStore = create<BrandingState>((set, get) => {
  const initial = load();

  // Cross-tab sync — when localStorage[STORAGE_KEY] changes in another
  // tab (e.g. user edits branding on /login while the app is open in
  // another window, or vice-versa), re-hydrate this tab's store so the
  // sidebar / login screen stays consistent without a reload. Same-tab
  // edits go through setLogo/setCompanyName so they bypass this path.
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (e) => {
      if (e.key !== STORAGE_KEY) return;
      const fresh = load();
      const current = get();
      if (
        fresh.mode === current.mode &&
        fresh.logoDataUrl === current.logoDataUrl &&
        fresh.logoPngDataUrl === current.logoPngDataUrl &&
        fresh.companyName === current.companyName
      ) {
        return;
      }
      set(fresh);
    });
  }

  return {
    ...initial,
    options: loadOptions(),
    setOptions: (raw) => {
      const options = sanitizeOptions(raw);
      saveOptions(options);
      set({ options });
    },
    setLogo: (dataUrl, pngDataUrl = null) => {
      const current = get();
      if (!dataUrl) {
        const next: Persisted = {
          mode: current.companyName ? 'text' : 'default',
          logoDataUrl: null,
          logoPngDataUrl: null,
          companyName: current.companyName,
        };
        save(next);
        set(next);
        return;
      }
      const next: Persisted = {
        mode: 'logo',
        logoDataUrl: dataUrl,
        logoPngDataUrl: pngDataUrl,
        companyName: current.companyName,
      };
      save(next);
      const showLogoEdit = logoEditAfterLogoChange(current.logoDataUrl, dataUrl, current.options.showLogoEdit);
      if (showLogoEdit === current.options.showLogoEdit) {
        set(next);
        return;
      }
      const options = { ...current.options, showLogoEdit };
      saveOptions(options);
      set({ ...next, options });
    },
    setCompanyName: (name) => {
      const trimmed = name.trim().slice(0, 60);
      const current = get();
      // Logo wins over text — if a logo is set, we keep mode=logo
      // and just update the stored name so the user can flip back.
      const mode: BrandingMode =
        current.logoDataUrl ? 'logo' : trimmed ? 'text' : 'default';
      const next: Persisted = {
        mode,
        logoDataUrl: current.logoDataUrl,
        logoPngDataUrl: current.logoPngDataUrl,
        companyName: trimmed,
      };
      save(next);
      set(next);
    },
    reset: () => {
      const next: Persisted = { mode: 'default', logoDataUrl: null, logoPngDataUrl: null, companyName: '' };
      save(next);
      set(next);
    },
    hydrateFromServer: async () => {
      try {
        const r = await apiGet<ServerBranding>('/v1/branding/');
        useAppearanceStore.getState().setWorkspaceDefault(r.appearance ?? null);
        useAppearanceStore.getState().setWorkspaceMenu(r.appearance?.menu ?? null);
        get().setOptions(r);
        const next = fromServer(r);
        const current = get();
        if (
          next.mode === current.mode &&
          next.logoDataUrl === current.logoDataUrl &&
          next.logoPngDataUrl === current.logoPngDataUrl &&
          next.companyName === current.companyName
        ) {
          return;
        }
        save(next);
        set(next);
      } catch {
        /* offline / desktop without a reachable server - keep the local cache */
      }
    },
    persistToServer: async () => {
      const s = get();
      try {
        // Always a PUT: the server keeps fields this payload leaves out, so the
        // workspace appearance default survives a brand reset. A default brand
        // with no appearance removes the stored file, as DELETE did.
        await apiPut('/v1/branding/', {
          mode: s.mode,
          logo_data_url: s.logoDataUrl,
          logo_png_data_url: s.logoPngDataUrl,
          company_name: s.companyName,
          show_logo_edit: s.options.showLogoEdit,
        });
        return true;
      } catch {
        // Non-admin (403), pre-auth (401) or offline: the local change still
        // applies, we just could not make it workspace-wide.
        return false;
      }
    },
  };
});

export const BRANDING_MAX_LOGO_BYTES = MAX_LOGO_BYTES;
