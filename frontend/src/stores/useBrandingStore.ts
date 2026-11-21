// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Custom branding for the sidebar header.
 *
 * Lets users white-label the in-app sidebar with their own company
 * logo (PNG/JPG/SVG) or company name. When set, the user's brand
 * shows prominently at the top of the sidebar; the
 * product wordmark moves below it at one-third the
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

/**
 * Where the in-app bug report is sent.
 *
 * `null` - the default - means the workspace has not chosen, and the channel is
 * then left out of the menu entirely rather than pointed somewhere by default. A
 * report carries the user's own words plus their environment, so the destination
 * is the operator's decision, not the product's.
 */
export interface SupportDestination {
  /** `url` opens a support page; `email` opens the user's mail client. */
  kind: 'url' | 'email';
  value: string;
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
   * Where the bug-report channel sends the user, or null to hide the channel.
   *
   * Server-backed and deliberately NOT mirrored to localStorage: it is a
   * workspace decision, so a browser cache must not be able to disagree with it
   * or outlive it. See {@link Persisted}.
   */
  supportDestination: SupportDestination | null;
  /**
   * Whether the product shows its Legal link. Default true, server-backed, and
   * also not mirrored locally. Turning it off does not hide /legal or the
   * copyright line - only the footer link that points at them.
   */
  legalLinkVisible: boolean;
  /**
   * Whether this workspace asks PyPI and GitHub which release is newest.
   *
   * Default false, server-backed, and - like the two settings above it - never
   * mirrored to localStorage, because a browser cache that remembered "on" would
   * keep asking after an administrator turned it off. This is the one setting on
   * the record that starts a connection nobody in the workspace made, so it is
   * the one that waits to be asked for; About states which way it currently is.
   */
  updateCheckEnabled: boolean;
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
  /** Admin-only in effect: {@link persistToServer} is what makes it stick. */
  setSupportDestination: (destination: SupportDestination | null) => void;
  /** Admin-only in effect: {@link persistToServer} is what makes it stick. */
  setLegalLinkVisible: (visible: boolean) => void;
  /** Admin-only in effect: {@link persistToServer} is what makes it stick. */
  setUpdateCheckEnabled: (enabled: boolean) => void;
  /** Clear all customisation and return to the default product brand. */
  reset: () => void;
  /**
   * Pull the workspace branding from the server and apply it (the server is the
   * source of truth, so it overrides the local cache). Best-effort: on any
   * failure the local cache is kept, so the desktop build and offline use keep
   * working. The endpoint is public, so this is safe to call before sign-in -
   * the login page does, so invited users see the workspace brand.
   */
  hydrateFromServer: () => Promise<void>;
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
  /** Workspace default UI appearance (style axes plus `menu`); see useAppearanceStore. */
  appearance?: { menu?: unknown } | null;
  support_destination?: { kind?: string; value?: string } | null;
  legal_link_visible?: boolean;
  update_check_enabled?: boolean;
}

/**
 * Coerce the three server-only settings out of a branding payload.
 *
 * Kept apart from {@link fromServer} on purpose: that one returns a
 * {@link Persisted}, i.e. exactly the four fields this browser caches, and these
 * three must never enter it.
 */
function serverSettings(r: ServerBranding): {
  supportDestination: SupportDestination | null;
  legalLinkVisible: boolean;
  updateCheckEnabled: boolean;
} {
  const raw = r.support_destination;
  const value = typeof raw?.value === 'string' ? raw.value.trim() : '';
  const supportDestination: SupportDestination | null =
    raw && (raw.kind === 'url' || raw.kind === 'email') && value ? { kind: raw.kind, value } : null;
  // Only an exact false hides the Legal link. A missing key, a corrupt file or a
  // hand-edited "yes" all fall to the safe default, which is to show it.
  //
  // The version check is the mirror image, and for the same reason read from the
  // other side: only an exact true starts it. The server sanitises to the same
  // rule, so this is not a second opinion - it is the same answer, and a payload
  // that lacks the key cannot be read as permission to phone out.
  return {
    supportDestination,
    legalLinkVisible: r.legal_link_visible !== false,
    updateCheckEnabled: r.update_check_enabled === true,
  };
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
    supportDestination: null,
    legalLinkVisible: true,
    updateCheckEnabled: false,
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
      set(next);
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
    setSupportDestination: (destination) => set({ supportDestination: destination }),
    setLegalLinkVisible: (visible) => set({ legalLinkVisible: visible }),
    setUpdateCheckEnabled: (enabled) => set({ updateCheckEnabled: enabled }),
    hydrateFromServer: async () => {
      try {
        const r = await apiGet<ServerBranding>('/v1/branding/');
        useAppearanceStore.getState().setWorkspaceDefault(r.appearance ?? null);
        useAppearanceStore.getState().setWorkspaceMenu(r.appearance?.menu ?? null);
        const next = fromServer(r);
        const current = get();
        // Applied BEFORE the comparison below, which only looks at the four
        // mirrored brand fields. Set them afterwards and an operator who changes
        // nothing but the support destination - or nothing but the Legal link, or
        // nothing but the version check - is ignored on every load, because the
        // brand fields are unchanged and this function returns early before
        // reaching them.
        const settings = serverSettings(r);
        if (
          settings.supportDestination?.kind !== current.supportDestination?.kind ||
          settings.supportDestination?.value !== current.supportDestination?.value ||
          settings.legalLinkVisible !== current.legalLinkVisible ||
          settings.updateCheckEnabled !== current.updateCheckEnabled
        ) {
          set(settings);
        }
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
          support_destination: s.supportDestination,
          legal_link_visible: s.legalLinkVisible,
          update_check_enabled: s.updateCheckEnabled,
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
