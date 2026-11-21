// Design module (ERP side of the design editor link).
/** Decisions of the offer points and the editor launcher, kept free of React so they can be tested alone. */

export const MODULE_KEY = 'design';
export const DISMISS_KEY = 'oe_design_offer_dismissed';
export const INSTALLER_SEEN_KEY = 'oe_design_installer_hint_seen';

/** The shape of a `ddc-link/1` file as the server returns it. */
export interface LinkFile {
  schema: 'ddc-link/1';
  erp_url: string;
  project_id: string;
  project_name: string;
  code: string;
  expires_at: string;
  action: 'new' | 'open';
  revision_id?: string | null;
}

export type OfferVariant = 'tour' | 'empty' | 'drawings';

/**
 * Whether an offer point shows. The module being switched on, or the person having said "not now" to the
 * tour question, hides it. The empty-state banner ignores the tour dismissal: a person who skipped the
 * question at set-up may still reach for models later, and the banner is quiet.
 */
export function shouldOffer(variant: OfferVariant, moduleEnabled: boolean, dismissed: boolean): boolean {
  if (moduleEnabled) return false;
  return variant === 'tour' ? !dismissed : true;
}

/** A safe file name for the link file of a project. */
export function linkFileName(projectName: string): string {
  const slug = projectName
    .replace(/ß/g, 'ss')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return `${slug || 'project'}.ddclink`;
}

/** Serialized link file: the editor reads it as UTF-8 JSON. */
export function serializeLink(link: LinkFile): string {
  return `${JSON.stringify(link, null, 2)}\n`;
}

/** The design editor's public site: downloads, editions and documentation. */
export const EDITOR_SITE = 'https://openconstructiondesign.com/';

/** A build may point at its own installer (https only); otherwise the editor's public site. */
export function installerUrl(env: Record<string, string | undefined>): string {
  const raw = (env.VITE_DESIGN_EDITOR_URL ?? '').trim();
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' ? url.toString() : EDITOR_SITE;
  } catch {
    return EDITOR_SITE;
  }
}

/** A link code lives a few minutes; tell the page when to stop offering the file it holds. */
export function linkExpired(link: LinkFile, now: number = Date.now()): boolean {
  const at = Date.parse(link.expires_at);
  return Number.isNaN(at) || at <= now;
}
