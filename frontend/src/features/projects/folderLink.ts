// The project's external folder link: a shared drive or cloud folder outside
// the platform. Mirrors the server rule (`validate_external_folder_url`):
// http(s), file or smb URLs and UNC paths, at most 500 characters.

export const FOLDER_LINK_MAX = 500;

const SCHEME_RE = /^(https?|file|smb):\/\/\S+$/i;
const UNC_RE = /^\\\\[^\\/\s]+\\\S+$/;
// eslint-disable-next-line no-control-regex
const CONTROL_RE = /[\x00-\x1f\x7f]/;

export type FolderLinkProblem = 'too_long' | 'format' | null;

/** Why a draft cannot be saved, or null when it can (empty clears the link). */
export function folderLinkProblem(raw: string): FolderLinkProblem {
  const v = raw.trim();
  if (v === '') return null;
  if (v.length > FOLDER_LINK_MAX) return 'too_long';
  if (CONTROL_RE.test(v)) return 'format';
  return SCHEME_RE.test(v) || UNC_RE.test(v) ? null : 'format';
}

/** An href the browser can follow; UNC paths become file: URLs. */
export function folderLinkHref(link: string): string {
  const v = link.trim();
  if (UNC_RE.test(v)) return `file:${v.replace(/\\/g, '/')}`;
  return v;
}
